import 'package:material_ui/material_ui.dart';

import 'engine.dart';
import 'settings.dart';

/// Settings: provider, API key (stored only on this computer), model, limits, engine location.
class SettingsPage extends StatefulWidget {
  final AppSettings settings;
  final EngineRunner runner;
  const SettingsPage({super.key, required this.settings, required this.runner});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late String _provider = widget.settings.provider;
  late final _geminiKey = TextEditingController(text: widget.settings.geminiKey);
  late final _claudeKey = TextEditingController(text: widget.settings.claudeKey);
  late final _model = TextEditingController(text: widget.settings.model);
  late final _rpm = TextEditingController(text: widget.settings.rpm);
  late final _rpd = TextEditingController(text: widget.settings.rpd);
  late final _engineDir = TextEditingController(text: widget.settings.engineDir);
  late final _python = TextEditingController(text: widget.settings.pythonPath);
  bool _showKey = false;
  bool _testing = false;
  String? _testResult;

  AppSettings _current() => AppSettings(
        provider: _provider,
        geminiKey: _geminiKey.text.trim(),
        claudeKey: _claudeKey.text.trim(),
        model: _model.text.trim(),
        rpm: _rpm.text.trim(),
        rpd: _rpd.text.trim(),
        engineDir: _engineDir.text.trim(),
        pythonPath: _python.text.trim(),
      );

  Future<void> _save() async {
    final s = widget.settings, c = _current();
    s
      ..provider = c.provider
      ..geminiKey = c.geminiKey
      ..claudeKey = c.claudeKey
      ..model = c.model
      ..rpm = c.rpm
      ..rpd = c.rpd
      ..engineDir = c.engineDir
      ..pythonPath = c.pythonPath;
    try {
      await s.save();
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Не успях да запазя настройките: $e')));
      }
    }
  }

  Future<void> _testKey() async {
    setState(() {
      _testing = true;
      _testResult = null;
    });
    String result = 'Няма отговор от двигателя.';
    await for (final e in widget.runner.testKey(_current())) {
      if (e is ModelsEvent) {
        result = 'Ключът работи. Налични модели: ${e.models.length}'
            '${e.models.isEmpty ? '' : ' (напр. ${e.models.take(3).join(', ')})'}';
      } else if (e is ErrorEvent) {
        result = 'Ключът не работи: ${e.message}';
      }
    }
    if (mounted) {
      setState(() {
        _testing = false;
        _testResult = result;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final engine = locateEngine(_current());
    const gap = SizedBox(height: 16);
    return Scaffold(
      appBar: AppBar(title: const Text('Настройки')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Доставчик на превода', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'gemini', label: Text('Gemini')),
              ButtonSegment(value: 'ollama', label: Text('Ollama (локално)')),
              ButtonSegment(value: 'claude', label: Text('Claude (платен)')),
            ],
            selected: {_provider},
            onSelectionChanged: (v) => setState(() {
              _provider = v.first;
              _testResult = null;
            }),
          ),
          gap,
          if (_provider == 'gemini') ...[
            _keyField(_geminiKey, 'Gemini API ключ'),
            const SizedBox(height: 8),
            Row(children: [
              OutlinedButton(
                onPressed: _testing ? null : _testKey,
                child: _testing
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('Тествай ключа'),
              ),
              const SizedBox(width: 12),
              if (_testResult != null) Expanded(child: SelectableText(_testResult!)),
            ]),
            const SizedBox(height: 4),
            Text('Безплатен ключ: aistudio.google.com. Ключът се пази само на този компютър.',
                style: Theme.of(context).textTheme.bodySmall),
          ],
          if (_provider == 'claude') _keyField(_claudeKey, 'Anthropic API ключ'),
          gap,
          TextField(
            controller: _model,
            decoration: InputDecoration(
              labelText: 'Модел (празно = по подразбиране)',
              helperText: _provider == 'gemini' ? 'Копирай точното име на модела от Google AI Studio.' : null,
              border: const OutlineInputBorder(),
            ),
          ),
          if (_provider == 'gemini') ...[
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: [
              for (final p in geminiPresets.entries)
                ActionChip(
                  label: Text(p.key),
                  onPressed: () => setState(() {
                    _model.text = p.value.$1;
                    _rpm.text = p.value.$2;
                    _rpd.text = p.value.$3;
                  }),
                ),
            ]),
          ],
          if (_provider != 'ollama') ...[
            gap,
            Row(children: [
              Expanded(child: _numberField(_rpm, 'Заявки в минута')),
              const SizedBox(width: 12),
              Expanded(child: _numberField(_rpd, 'Заявки на ден')),
            ]),
          ],
          const Divider(height: 40),
          Text('Двигател', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          TextField(
            controller: _engineDir,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Папка на двигателя (празно = вграденият)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _python,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Python (празно = автоматично)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            engine == null ? engineNotFound : 'Ще се използва: ${engine.executable}\nв папка: ${engine.workingDir}',
            style: TextStyle(color: engine == null ? Colors.red : null),
          ),
          gap,
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton(onPressed: _save, child: const Text('Запази')),
          ),
        ],
      ),
    );
  }

  Widget _keyField(TextEditingController c, String label) => TextField(
        controller: c,
        obscureText: !_showKey,
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
          suffixIcon: IconButton(
            tooltip: _showKey ? 'Скрий' : 'Покажи',
            icon: Icon(_showKey ? Icons.visibility_off : Icons.visibility),
            onPressed: () => setState(() => _showKey = !_showKey),
          ),
        ),
      );

  Widget _numberField(TextEditingController c, String label) => TextField(
        controller: c,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(labelText: '$label (празно = по подразбиране)', border: const OutlineInputBorder()),
      );
}
