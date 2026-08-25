import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:eclamp_flutter/screens.dart';
import 'package:eclamp_flutter/store.dart';
import 'package:eclamp_flutter/theme.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('splash no overflow', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: const Splash(onStart: _doNothing),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('login no overflow', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Login(
          onBack: _doNothing,
          onSignup: _doNothing,
          onSuccess: _doNothing,
        ),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('signup no overflow', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 1800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Signup(
          onBack: _doNothing,
          onLogin: _doNothing,
          onSuccess: _doNothing,
        ),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('login shows error and succeeds with valid credentials', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    var succeeded = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Login(
          onBack: _doNothing,
          onSignup: _doNothing,
          onSuccess: () => succeeded = true,
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Login'));
    await tester.pump();
    expect(find.text('Enter a valid email and password.'), findsOneWidget);
    expect(succeeded, isFalse);

    await tester.enterText(_field('e.g. emma@campus.edu'), 'emma@campus.edu');
    await tester.enterText(_field('Enter your password'), 'secret123');
    await tester.tap(find.text('Login'));
    await tester.pumpAndSettle();
    expect(succeeded, isTrue);
    expect(AppStore.instance.isLoggedIn, isTrue);
    expect(AppStore.instance.user!.email, 'emma@campus.edu');
  });

  testWidgets('signup validates password mismatch then succeeds', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(411 * 2, 1800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    var succeeded = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Signup(
          onBack: _doNothing,
          onLogin: _doNothing,
          onSuccess: () => succeeded = true,
        ),
      ),
    );
    await tester.pump();
    await tester.enterText(_field('e.g. Emma Johnson'), 'Emma Johnson');
    await tester.enterText(_field('e.g. emma@campus.edu'), 'emma@campus.edu');
    await tester.enterText(_field('e.g. ECO-2024-001'), 'ECO-2024-001');
    await tester.enterText(_field('e.g. +1 555 123 4567'), '+15551234567');
    await tester.enterText(_field('At least 6 characters'), 'secret123');
    await tester.enterText(_field('Re-enter your password'), 'different');
    await tester.tap(find.text('Sign up'));
    await tester.pump();
    expect(find.text('Passwords do not match.'), findsOneWidget);
    expect(succeeded, isFalse);

    await tester.enterText(_field('Re-enter your password'), 'secret123');
    await tester.tap(find.text('Sign up'));
    await tester.pumpAndSettle();
    expect(succeeded, isTrue);
    expect(AppStore.instance.isLoggedIn, isTrue);
    expect(AppStore.instance.user!.name, 'Emma Johnson');
    expect(AppStore.instance.user!.studentId, 'ECO-2024-001');
  });
}

Finder _field(String hint) => find.byWidgetPredicate(
  (w) => w is TextField && w.decoration?.hintText == hint,
);

void _doNothing() {}
