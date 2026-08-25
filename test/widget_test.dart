import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:eclamp_flutter/main.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('Ecolamp shows splash', (WidgetTester tester) async {
    await tester.pumpWidget(const EcolampApp());
    await tester.pumpAndSettle();
    expect(find.text('Ecolamp'), findsWidgets);
    expect(find.text('Get Started'), findsOneWidget);
  });
}
