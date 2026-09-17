import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:scwt_flutter/main.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('SCWT shows splash', (WidgetTester tester) async {
    await tester.pumpWidget(const SCWTApp());
    await tester.pumpAndSettle();
    expect(find.text('SCWT'), findsWidgets);
    expect(find.text('Get Started'), findsOneWidget);
  });
}
