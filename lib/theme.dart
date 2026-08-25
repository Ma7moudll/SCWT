import 'package:flutter/material.dart';

class AppColors {
  static const background = Color(0xFFf4fbf7);
  static const foreground = Color(0xFF17231f);
  static const card = Color(0xFFFFFFFF);
  static const border = Color(0xFFdcece3);
  static const primary = Color(0xFF19b957);
  static const primaryForeground = Color(0xFFFFFFFF);
  static const mutedForeground = Color(0xFF72827b);
  static const darkGreen = Color(0xFF006b4f);

  static const splashTop = Color(0xFF005c43);
  static const splashMid = Color(0xFF009451);
  static const splashBottom = Color(0xFF003e31);

  static const stepBlue = Color(0xFF1982d1);
  static const stepBlueBg = Color(0xFFedf5ff);

  // metric tones
  static const orange = Color(0xFFffad19);
  static const purple = Color(0xFF8474e8);
  static const green = Color(0xFF20a455);
  static const violet = Color(0xFF9661dd);
  static const blue = Color(0xFF3e9de5);

  static const successGreen = Color(0xFF15964b);
  static const lightGreenBg = Color(0xFFe8f8ee);
  static const red = Color(0xFFc23c34);
  static const notice = Color(0xFFf04f45);
  static const statusYellow = Color(0xFFffb126);
}

ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
      surface: AppColors.card,
    ),
    scaffoldBackgroundColor: AppColors.background,
    fontFamily: 'sans-serif',
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(
      bodyColor: AppColors.foreground,
      displayColor: AppColors.foreground,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      foregroundColor: AppColors.foreground,
    ),
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {TargetPlatform.android: FadeUpwardsPageTransitionsBuilder()},
    ),
  );
}
