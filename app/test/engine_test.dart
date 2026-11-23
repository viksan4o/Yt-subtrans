import 'dart:io';

import 'package:bg_subs/engine.dart';
import 'package:bg_subs/settings.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('parses every engine event', () {
    expect(parseEvent('{"event":"progress","done":3,"total":10}'),
        isA<ProgressEvent>().having((e) => e.total, 'total', 10));
    expect(parseEvent('{"event":"waiting","message":"Чакам"}'), isA<WaitingEvent>());
    expect(parseEvent('{"event":"quota","message":"Дневният лимит е изчерпан."}'), isA<QuotaEvent>());
    expect(parseEvent('{"event":"error","message":"лошо"}'),
        isA<ErrorEvent>().having((e) => e.message, 'message', 'лошо'));
    final done = parseEvent('{"event":"done","srt":"a.srt","cues":'
        '[{"id":1,"start":0.5,"end":2,"src":"Hi","tgt":"Здрасти","cps":3.1}]}') as DoneEvent;
    expect(done.cues.single.tgt, 'Здрасти');
    expect(done.cues.single.start, 0.5);
    expect(parseEvent('not json'), isNull);
    expect(parseEvent('{"event":"unknown"}'), isNull);
  });

  test('missing engine folder gives a Bulgarian error', () async {
    final s = AppSettings(engineDir: r'C:\no\such\folder');
    final events = await EngineRunner().translate('abc', s).toList();
    expect(events.single, isA<ErrorEvent>().having((e) => e.message, 'message', engineNotFound));
  });

  // Runs the real engine (fake provider, real YouTube captions) in a temp copy,
  // so nothing in the repo's engine folder or the user's cache is touched.
  test('real engine: link -> progress -> cue list', () async {
    final repo = Directory.current.parent.path;
    final tmp = await Directory.systemTemp.createTemp('bgsubs_test');
    try {
      await _copyDir(Directory('$repo\\engine\\subtrans'), Directory('${tmp.path}\\subtrans'));
      final s = AppSettings(provider: 'fake', engineDir: tmp.path, pythonPath: '$repo\\.venv\\Scripts\\python.exe');
      final runner = EngineRunner(extraEnv: {'SUBTRANS_CACHE_DIR': '${tmp.path}\\cache'});
      final events = await runner.translate('https://youtu.be/kko2T9Rm0Ak', s).toList();
      final error = events.whereType<ErrorEvent>().map((e) => e.message).join();
      expect(error, isEmpty);
      expect(events.whereType<ProgressEvent>(), isNotEmpty);
      final done = events.last as DoneEvent;
      expect(done.cues, isNotEmpty);
      expect(done.cues.first.tgt, startsWith('[BG]'));
    } finally {
      await tmp.delete(recursive: true);
    }
  }, timeout: const Timeout(Duration(minutes: 2)));
}

Future<void> _copyDir(Directory from, Directory to) async {
  await to.create(recursive: true);
  await for (final e in from.list()) {
    final name = e.uri.pathSegments.lastWhere((p) => p.isNotEmpty);
    if (name == '__pycache__') continue;
    if (e is Directory) {
      await _copyDir(e, Directory('${to.path}\\$name'));
    } else if (e is File) {
      await e.copy('${to.path}\\$name');
    }
  }
}
