import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:eclamp_flutter/main.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('navigate to home after login', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const EcolampApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('Get Started'));
    await tester.pumpAndSettle();

    // Invalid credentials keep the user on the Login screen.
    await tester.enterText(find.byType(TextField).at(0), 'not-an-email');
    await tester.enterText(find.byType(TextField).at(1), 'secret123');
    await tester.tap(find.text('Login'));
    await tester.pumpAndSettle();
    expect(find.text('Enter a valid email and password.'), findsOneWidget);

    // Valid credentials land on Home.
    await tester.enterText(find.byType(TextField).at(0), 'emma@campus.edu');
    await tester.enterText(find.byType(TextField).at(1), 'secret123');
    await tester.tap(find.text('Login'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Hi,'), findsOneWidget);
    expect(find.text('Recycle Now'), findsOneWidget);
  });
}
