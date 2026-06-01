@echo off  
setlocal enabledelayedexpansion  
for /l %%y in (2025,1,2026) do (  
for /l %%m in (1,1,12) do (  
if %%y==2026 if %%m gtr 6 exit /b  
for /l %%d in (1,1,31) do (  
call :check_date %%y %%m %%d  
)  
)  
)  
exit /b  
:check_date  
set yy=%1  
set mm=%2  
set dd=%3  
call :date2julian %yy% %mm% %dd% jd  
set start_jd=2460681  
set end_jd=2460995  
if !jd! geq !start_jd! if !jd! leq !end_jd! (  
set fname=daily_news!yy!-!mm!-!dd!.md  
if not exist "!fname!" (  
echo # !yy!年!mm!月!dd!日 新闻日报 > "!fname!"  
echo.  
echo ## 国际局势  
echo.  
echo 待补充  
echo.  
echo ## 科技突破  
echo.  
echo 待补充  
echo.  
echo ## 财经数据  
echo.  
echo 待补充  
echo.  
echo ## 综合摘要  
echo.  
echo 待补充  
echo.  
echo ---  
echo AI生成  
)  
)  
exit /b  
:date2julian  
set /a a=(14-%2)/12  
set /a y=%1+4800-a  
set /a m=%2+12*a-3  
set /a jd=%3+(153*m+2)/5+365*y+y/4-y/100+y/400-32045  
set %4=!jd!  
