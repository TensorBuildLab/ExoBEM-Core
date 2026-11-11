@echo off
rem Thermonaut build helper (Windows, MSVC 2022 Build Tools, Ninja).
rem Usage: planetary\tools\build.bat [configure] [jobs]
setlocal
set ROOT=%~dp0..\..
set BUILD=%ROOT%\build
set JOBS=%2
if "%JOBS%"=="" set JOBS=10
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set PATH=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%
if "%1"=="configure" (
  cmake -S "%ROOT%" -B "%BUILD%" -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLINK_WITH_PYTHON=OFF -DBUILD_FORTRAN=OFF -DENABLE_INSTALL_REMOTE=OFF || exit /b 1
)
cmake --build "%BUILD%" --target energyplus energyplus_tests -j %JOBS% || exit /b 1
echo BUILD-OK
