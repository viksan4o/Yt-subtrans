import 'dart:convert';
import 'dart:io';

/// User settings, saved as JSON in %APPDATA%\BG Subs\settings.json.
/// API keys live only in that file on this computer; they are never part of the repo.
class AppSettings {
  String provider; // gemini | ollama | claude
  String geminiKey;
  String claudeKey;
  String model; // empty = the engine's default model
  String rpm; // empty = engine default
  String rpd; // empty = engine default
  String engineDir; // empty = find the engine automatically
  String pythonPath; // empty = find Python automatically

  AppSettings({
    this.provider = 'gemini',
    this.geminiKey = '',
    this.claudeKey = '',
    this.model = '',
    this.rpm = '',
    this.rpd = '',
    this.engineDir = '',
    this.pythonPath = '',
  });

  String get apiKey => provider == 'claude' ? claudeKey : geminiKey;

  Map<String, dynamic> toJson() => {
        'provider': provider,
        'geminiKey': geminiKey,
        'claudeKey': claudeKey,
        'model': model,
        'rpm': rpm,
        'rpd': rpd,
        'engineDir': engineDir,
        'pythonPath': pythonPath,
      };

  factory AppSettings.fromJson(Map<String, dynamic> j) {
    String s(String k, [String d = '']) => (j[k] ?? d).toString();
    return AppSettings(
      provider: s('provider', 'gemini'),
      geminiKey: s('geminiKey'),
      claudeKey: s('claudeKey'),
      model: s('model'),
      rpm: s('rpm'),
      rpd: s('rpd'),
      engineDir: s('engineDir'),
      pythonPath: s('pythonPath'),
    );
  }

  static File get file {
    final base = Platform.environment['APPDATA'] ?? Directory.systemTemp.path;
    return File('$base${Platform.pathSeparator}BG Subs${Platform.pathSeparator}settings.json');
  }

  static Future<AppSettings> load() async {
    try {
      final f = file;
      if (await f.exists()) {
        return AppSettings.fromJson(jsonDecode(await f.readAsString()) as Map<String, dynamic>);
      }
    } catch (_) {
      // A broken settings file falls back to defaults.
    }
    return AppSettings();
  }

  Future<void> save() async {
    final f = file;
    await f.parent.create(recursive: true);
    await f.writeAsString(const JsonEncoder.withIndent('  ').convert(toJson()));
  }
}

/// Gemini presets: (model, RPM, RPD). Free-tier limits change; check Google AI Studio.
const geminiPresets = {
  'Качество (по подразбиране)': ('gemini-3.8-flash', '5', '20'),
  'Голям обем': ('gemini-3.5-flash-lite', '15', '500'),
};
