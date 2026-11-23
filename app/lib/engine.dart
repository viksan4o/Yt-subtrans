import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'settings.dart';

/// One translated subtitle cue from the engine. Times are in seconds.
class Cue {
  final int id;
  final double start;
  final double end;
  final String src;
  final String tgt;
  final double cps;

  const Cue(this.id, this.start, this.end, this.src, this.tgt, this.cps);

  factory Cue.fromJson(Map<String, dynamic> j) => Cue(
        (j['id'] as num).toInt(),
        (j['start'] as num).toDouble(),
        (j['end'] as num).toDouble(),
        (j['src'] ?? '').toString(),
        (j['tgt'] ?? '').toString(),
        ((j['cps'] ?? 0) as num).toDouble(),
      );
}

/// Events the engine prints, one JSON object per line.
sealed class EngineEvent {}

class ProgressEvent extends EngineEvent {
  final int done, total;
  ProgressEvent(this.done, this.total);
}

class WaitingEvent extends EngineEvent {
  final String message;
  WaitingEvent(this.message);
}

/// Free-tier daily limit reached; progress is saved and can resume later.
class QuotaEvent extends EngineEvent {
  final String message;
  QuotaEvent(this.message);
}

class ErrorEvent extends EngineEvent {
  final String message;
  ErrorEvent(this.message);
}

class DoneEvent extends EngineEvent {
  final List<Cue> cues;
  final String srtPath;
  DoneEvent(this.cues, this.srtPath);
}

class ModelsEvent extends EngineEvent {
  final List<String> models;
  ModelsEvent(this.models);
}

/// Parses one stdout line. Returns null for lines that are not engine events.
EngineEvent? parseEvent(String line) {
  line = line.trim();
  if (!line.startsWith('{')) return null;
  try {
    final j = jsonDecode(line) as Map<String, dynamic>;
    String msg() => (j['message'] ?? '').toString();
    switch (j['event']) {
      case 'progress':
        return ProgressEvent((j['done'] as num).toInt(), (j['total'] as num).toInt());
      case 'waiting':
        return WaitingEvent(msg());
      case 'quota':
        return QuotaEvent(msg());
      case 'error':
        return ErrorEvent(msg());
      case 'done':
        final cues = (j['cues'] as List).map((c) => Cue.fromJson(c as Map<String, dynamic>)).toList();
        return DoneEvent(cues, (j['srt'] ?? '').toString());
      case 'models':
        return ModelsEvent((j['models'] as List).map((m) => m is Map ? '${m['name'] ?? m}' : '$m').toList());
    }
  } catch (_) {
    // Not valid JSON or an unexpected shape: ignore the line.
  }
  return null;
}

/// How to start the engine: a program, the arguments that come before the command, and a folder.
class EngineCommand {
  final String executable;
  final List<String> prefix;
  final String workingDir;
  const EngineCommand(this.executable, this.prefix, this.workingDir);
}

String _join(String a, String b) => '$a${Platform.pathSeparator}$b';

/// Finds the engine. A folder from the settings wins; otherwise the bundled engine next to the app
/// (engine\subtrans.exe, built in the release milestone), then an `engine` source folder found by
/// walking up from the app and from the current folder (the developer setup in this repo).
EngineCommand? locateEngine(AppSettings s) {
  final candidates = <String>[];
  if (s.engineDir.trim().isNotEmpty) {
    candidates.add(s.engineDir.trim());
  } else {
    for (final start in [File(Platform.resolvedExecutable).parent, Directory.current]) {
      Directory? d = start.absolute;
      for (var i = 0; i < 10 && d != null; i++) {
        candidates.add(_join(d.path, 'engine'));
        final parent = d.parent;
        d = parent.path == d.path ? null : parent;
      }
    }
  }
  for (final dir in candidates) {
    final exe = _join(dir, 'subtrans.exe');
    if (File(exe).existsSync()) return EngineCommand(exe, const [], dir);
    if (File(_join(_join(dir, 'subtrans'), 'cli.py')).existsSync()) {
      return EngineCommand(_findPython(s, dir), const ['-m', 'subtrans.cli'], dir);
    }
  }
  return null;
}

String _findPython(AppSettings s, String engineDir) {
  if (s.pythonPath.trim().isNotEmpty) return s.pythonPath.trim();
  final venv = _join(_join('.venv', 'Scripts'), 'python.exe');
  for (final base in [Directory(engineDir).parent.path, engineDir]) {
    final p = _join(base, venv);
    if (File(p).existsSync()) return p;
  }
  return 'python';
}

const engineNotFound = 'Не намирам двигателя (папката engine). Отвори Настройки и посочи папката му.';

/// Runs the engine as a subprocess and turns its output into events.
class EngineRunner {
  /// Extra environment variables for the engine (tests use it for a separate cache folder).
  final Map<String, String> extraEnv;
  EngineRunner({this.extraEnv = const {}});

  Process? _process;
  bool _stopped = false;

  bool get running => _process != null;

  /// Translates a YouTube link. The stream always ends with Done, Error or Quota.
  Stream<EngineEvent> translate(String url, AppSettings s) {
    final args = ['translate', url, '--provider', s.provider];
    if (s.model.trim().isNotEmpty) args.addAll(['--model', s.model.trim()]);
    if (s.provider != 'ollama') {
      if (int.tryParse(s.rpm.trim()) != null) args.addAll(['--rpm', s.rpm.trim()]);
      if (int.tryParse(s.rpd.trim()) != null) args.addAll(['--rpd', s.rpd.trim()]);
    }
    return _run(args, s);
  }

  /// Makes one small request with the Gemini key (lists the models it can use).
  Stream<EngineEvent> testKey(AppSettings s) => _run(['list-models'], s);

  void stop() {
    _stopped = true;
    _process?.kill();
  }

  Stream<EngineEvent> _run(List<String> args, AppSettings s) {
    final out = StreamController<EngineEvent>();
    () async {
      final cmd = locateEngine(s);
      if (cmd == null) {
        out.add(ErrorEvent(engineNotFound));
        await out.close();
        return;
      }
      // Keys go through the environment, not the command line, so they never show in process lists.
      final env = <String, String>{'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', ...extraEnv};
      if (s.geminiKey.trim().isNotEmpty) env['GEMINI_API_KEY'] = s.geminiKey.trim();
      if (s.claudeKey.trim().isNotEmpty) env['ANTHROPIC_API_KEY'] = s.claudeKey.trim();
      _stopped = false;
      final Process p;
      try {
        p = await Process.start(cmd.executable, [...cmd.prefix, ...args],
            workingDirectory: cmd.workingDir, environment: env);
      } on ProcessException catch (e) {
        out.add(ErrorEvent('Не мога да стартирам двигателя (${cmd.executable}). '
            'Провери дали Python е инсталиран или посочи пътя до него в Настройки.\n${e.message}'));
        await out.close();
        return;
      }
      _process = p;
      var finished = false;
      final stderr = StringBuffer();
      final errDone = p.stderr.transform(utf8.decoder).forEach(stderr.write);
      await for (final line in p.stdout.transform(utf8.decoder).transform(const LineSplitter())) {
        final e = parseEvent(line);
        if (e == null) continue;
        if (e is DoneEvent || e is ErrorEvent || e is QuotaEvent || e is ModelsEvent) finished = true;
        out.add(e);
      }
      final code = await p.exitCode;
      await errDone;
      _process = null;
      if (!finished) {
        if (_stopped) {
          out.add(ErrorEvent('Преводът е спрян. Напредъкът е запазен и ще продължи при следващо пускане.'));
        } else {
          out.add(ErrorEvent(_crashMessage(code, stderr.toString())));
        }
      }
      await out.close();
    }();
    return out.stream;
  }
}

String _crashMessage(int code, String stderr) {
  final tail = stderr.trim().split('\n').where((l) => l.trim().isNotEmpty).toList();
  final last = tail.isEmpty ? '' : tail.last.trim();
  if (last.contains('No module named')) {
    return 'Липсват Python пакети за двигателя. В папката engine пусни: pip install -r requirements.txt\n$last';
  }
  return 'Двигателят спря неочаквано (код $code).${last.isEmpty ? '' : '\n$last'}';
}
