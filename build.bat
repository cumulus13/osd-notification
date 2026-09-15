@echo off
rmdir /q /s dist
python -m build
if %errorlevel% == 0 goto upload
goto end

:upload
twine upload dist\*
goto end

:end

