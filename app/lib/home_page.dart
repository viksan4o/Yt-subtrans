import 'dart:async';

import 'package:material_ui/material_ui.dart';

import 'engine.dart';
import 'settings.dart';
import 'settings_page.dart';

/// Main screen: link field, "Преведи", progress, errors, then the finished cue list.
class HomePage extends StatefulWidget {
  final AppSettings settings;
  final EngineRunner runner;
  const HomePage({super.key, required this.settings, required this.runner});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _link = TextEditingController();
  StreamSubscription<EngineEvent>? _sub;
  bool _running = false;
  int _done = 0, _total = 0;
  String? _status; // what is happening now
  String? _error; // red card
  String? _warning; // orange card (daily limit)
  List<Cue> _cues = [];

  @override
  void dispose() {
    _sub?.cancel();
    widget.runner.stop();
    _link.dispose();
    super.dispose();
  }

  void _translate() {
    final url = _link.text.trim();
    if (url.isEmpty) {
      setState(() => _error = 'Постави линк към YouTube видео.');
      return;
    }
    setState(() {
      _running = true;
      _done = _total = 0;
      _status = 'Свалям субтитрите от YouTube…';
      _error = _warning = null;
      _cues = [];
    });
    _sub = widget.runner.translate(url, widget.settings).listen(_onEvent, onDone: () {
      if (mounted) setState(() => _running = false);
    });
  }

  void _onEvent(EngineEvent e) {
    if (!mounted) return;
    setState(() {
      switch (e) {
        case ProgressEvent():
          _done = e.done;
          _total = e.total;
          _status = 'Превеждам: ${e.done} от ${e.total} реплики';
        case WaitingEvent():
          _status = e.message;
        case QuotaEvent():
          _warning = e.message;
          _status = null;
        case ErrorEvent():
          _error = e.message;
          _status = null;
        case DoneEvent():
          _cues = e.cues;
          _done = _total = e.cues.length;
          _status = 'Готово: ${e.cues.length} реплики';
        case ModelsEvent():
          break;
      }
    });
  }

  Future<void> _openSettings() async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => SettingsPage(settings: widget.settings, runner: widget.runner)));
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BG Subs'),
        actions: [
          IconButton(
            tooltip: 'Настройки',
            icon: const Icon(Icons.settings),
            onPressed: _running ? null : _openSettings,
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _link,
                  enabled: !_running,
                  decoration: const InputDecoration(
                    labelText: 'Линк към YouTube видео',
                    hintText: 'https://www.youtube.com/watch?v=…',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _running ? null : _translate(),
                ),
              ),
              const SizedBox(width: 12),
              _running
                  ? OutlinedButton.icon(
                      onPressed: widget.runner.stop,
                      icon: const Icon(Icons.stop),
                      label: const Text('Спри'))
                  : FilledButton.icon(
                      onPressed: _translate,
                      icon: const Icon(Icons.translate),
                      label: const Text('Преведи')),
            ]),
            const SizedBox(height: 8),
            Text('Доставчик: ${_providerName(widget.settings.provider)}'
                '${widget.settings.model.isEmpty ? '' : ' · ${widget.settings.model}'}',
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            if (_running) LinearProgressIndicator(value: _total > 0 ? _done / _total : null),
            if (_status != null)
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(_status!)),
            if (_warning != null) _Notice(_warning!, Colors.orange, Icons.hourglass_bottom),
            if (_error != null) _Notice(_error!, Colors.red, Icons.error_outline),
            const SizedBox(height: 12),
            Expanded(child: _cues.isEmpty ? const SizedBox() : _CueList(_cues)),
          ],
        ),
      ),
    );
  }
}

String _providerName(String p) =>
    {'gemini': 'Gemini', 'ollama': 'Ollama (локално)', 'claude': 'Claude'}[p] ?? p;

class _Notice extends StatelessWidget {
  final String text;
  final MaterialColor color;
  final IconData icon;
  const _Notice(this.text, this.color, this.icon);

  @override
  Widget build(BuildContext context) => Card(
        color: color.shade50,
        margin: const EdgeInsets.only(top: 12),
        child: ListTile(
          leading: Icon(icon, color: color.shade700),
          title: SelectableText(text, style: TextStyle(color: color.shade900)),
        ),
      );
}

class _CueList extends StatelessWidget {
  final List<Cue> cues;
  const _CueList(this.cues);

  @override
  Widget build(BuildContext context) {
    final small = Theme.of(context).textTheme.bodySmall;
    return ListView.separated(
      itemCount: cues.length,
      separatorBuilder: (_, _) => const Divider(height: 1),
      itemBuilder: (_, i) {
        final c = cues[i];
        return ListTile(
          dense: true,
          leading: Text(formatTime(c.start), style: small),
          title: Text(c.tgt),
          subtitle: Text(c.src),
          trailing: c.cps > 21
              ? Tooltip(
                  message: 'Твърде бързо за четене (${c.cps.toStringAsFixed(1)} знака/сек)',
                  child: const Icon(Icons.speed, color: Colors.orange))
              : null,
        );
      },
    );
  }
}

/// 83.4 -> "1:23", 3723 -> "1:02:03".
String formatTime(double seconds) {
  final t = seconds.floor();
  final h = t ~/ 3600, m = (t % 3600) ~/ 60, s = t % 60;
  String two(int n) => n.toString().padLeft(2, '0');
  return h > 0 ? '$h:${two(m)}:${two(s)}' : '$m:${two(s)}';
}
