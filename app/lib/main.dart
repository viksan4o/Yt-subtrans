import 'package:material_ui/material_ui.dart';

import 'engine.dart';
import 'home_page.dart';
import 'settings.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = await AppSettings.load();
  runApp(BgSubsApp(settings: settings, runner: EngineRunner()));
}

class BgSubsApp extends StatelessWidget {
  final AppSettings settings;
  final EngineRunner runner;
  const BgSubsApp({super.key, required this.settings, required this.runner});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BG Subs',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
      home: HomePage(settings: settings, runner: runner),
    );
  }
}
