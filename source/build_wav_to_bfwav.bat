@echo off
echo =========================================
echo  Switch BFWAV ^& BFSTM Converter -- Build Script
echo =========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo [1/3] Checking dependencies...
pip show pyinstaller >nul 2>&1
if errorlevel 1 ( pip install pyinstaller )
pip show pydub >nul 2>&1
if errorlevel 1 ( pip install pydub )
pip show imageio-ffmpeg >nul 2>&1
if errorlevel 1 ( pip install imageio-ffmpeg )
pip show windnd >nul 2>&1
if errorlevel 1 ( pip install windnd )
pip show pillow >nul 2>&1
if errorlevel 1 ( pip install pillow )

echo.
echo [2/3] Building executable...
if exist "build" ( rmdir /s /q "build" )
if exist "dist"  ( rmdir /s /q "dist"  )
pyinstaller ^
    --onedir ^
    --windowed ^
    --name "Switch_BFWAV_BFSTM_Converter" ^
    --icon "switch_red.ico" ^
    --add-data "converter_core.py;." ^
    --add-binary "NW4F_WaveConverter.exe;." ^
    --add-binary "VGAudioCli.exe;." ^
    --add-binary "vgmstream-cli.exe;." ^
    --add-binary "SoundFoundation.dll;." ^
    --add-binary "SoundFoundation.LegacyFormats.dll;." ^
    --add-binary "SoundFoundationCafe.dll;." ^
    --add-binary "SoundFoundationCtr.dll;." ^
    --add-binary "SoundMakerFramework.dll;." ^
    --add-binary "SoundRuntimeCafe.dll;." ^
    --add-binary "ToolDevelopmentKit.dll;." ^
    --add-binary "WaveCodecCafe.dll;." ^
    --add-binary "avcodec-vgmstream-59.dll;." ^
    --add-binary "avformat-vgmstream-59.dll;." ^
    --add-binary "avutil-vgmstream-57.dll;." ^
    --add-binary "libatrac9.dll;." ^
    --add-binary "libcelt-0061.dll;." ^
    --add-binary "libcelt-0110.dll;." ^
    --add-binary "libg719_decode.dll;." ^
    --add-binary "libmpg123-0.dll;." ^
    --add-binary "libspeex-1.dll;." ^
    --add-binary "libvorbis.dll;." ^
    --add-binary "swresample-vgmstream-4.dll;." ^
    --hidden-import windnd ^
    --add-data "switch_red.png;." ^
    audio_to_bfwav.py

echo.
if exist "dist\Switch_BFWAV_BFSTM_Converter\Switch_BFWAV_BFSTM_Converter.exe" (
    echo [3/3] Success!
    echo.
    echo dist\Switch_BFWAV_BFSTM_Converter\Switch_BFWAV_BFSTM_Converter.exe is ready.
) else (
    echo [ERROR] Build failed.
)

pause
