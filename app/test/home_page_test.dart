import 'package:bg_subs/engine.dart';
import 'package:bg_subs/home_page.dart';
import 'package:bg_subs/settings.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

/// Pretends to be the engine: two progress steps, then the finished cues.
class FakeRunner extends EngineRunner {
  @override
  Stream<EngineEvent> translate(String url, AppSettings s) async* {
    yield ProgressEvent(0, 2);
    yield ProgressEvent(1, 2);
    yield DoneEvent([
      const Cue(1, 0, 2, 'Hello there', 'Здравей', 4),
      const Cue(2, 65, 66, 'That guy is so sweaty', 'Този е много потен', 30),
    ], 'x.bg.srt');
  }
}

class FailingRunner extends EngineRunner {
  @override
  Stream<EngineEvent> translate(String url, AppSettings s) async* {
    yield QuotaEvent('Дневният лимит е изчерпан. Продължи утре или смени модела.');
  }
}

Widget app(EngineRunner r) => MaterialApp(home: HomePage(settings: AppSettings(), runner: r));

void main() {
  testWidgets('pasting a link shows the finished cue list', (tester) async {
    await tester.pumpWidget(app(FakeRunner()));
    await tester.enterText(find.byType(TextField), 'https://youtu.be/abc');
    await tester.tap(find.text('Преведи'));
    await tester.pumpAndSettle();
    expect(find.text('Готово: 2 реплики'), findsOneWidget);
    expect(find.text('Здравей'), findsOneWidget);
    expect(find.text('Този е много потен'), findsOneWidget);
    expect(find.text('1:05'), findsOneWidget);
    expect(find.byIcon(Icons.speed), findsOneWidget); // too fast to read
  });

  testWidgets('empty link asks for a link', (tester) async {
    await tester.pumpWidget(app(FakeRunner()));
    await tester.tap(find.text('Преведи'));
    await tester.pump();
    expect(find.text('Постави линк към YouTube видео.'), findsOneWidget);
  });

  testWidgets('daily limit is shown', (tester) async {
    await tester.pumpWidget(app(FailingRunner()));
    await tester.enterText(find.byType(TextField), 'abc');
    await tester.tap(find.text('Преведи'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Дневният лимит'), findsOneWidget);
  });

  test('formatTime', () {
    expect(formatTime(83.4), '1:23');
    expect(formatTime(3723), '1:02:03');
  });
}
