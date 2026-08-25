import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:eclamp_flutter/screens.dart';
import 'package:eclamp_flutter/theme.dart';

void main() {
  testWidgets('home no overflow', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Material(child: Home(go: (_) {})),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
