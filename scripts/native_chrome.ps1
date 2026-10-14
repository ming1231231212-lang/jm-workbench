param([long]$Window=0,[int]$ExpectedProcessId=0,[string]$ExpectedProcessStarted='')
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$q=[Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type 'using System; using System.Runtime.InteropServices; public static class JmNativeChrome { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e); [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(Point p); [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h,uint f); [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p); [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId(); [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a,uint b,bool attach); [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h); [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int command); [StructLayout(LayoutKind.Sequential)] public struct Point { public int x; public int y; } public static bool Activate(IntPtr h) { if(IsIconic(h)) ShowWindow(h,9); if(GetForegroundWindow()==h) return true; if(SetForegroundWindow(h) && GetForegroundWindow()==h) return true; var f=GetForegroundWindow(); if(f==IntPtr.Zero) return false; uint p; uint foreground=GetWindowThreadProcessId(f,out p), current=GetCurrentThreadId(); bool joined=foreground!=current && AttachThreadInput(current,foreground,true); try { BringWindowToTop(h); SetForegroundWindow(h); return GetForegroundWindow()==h; } finally { if(joined) AttachThreadInput(current,foreground,false); } } }'
if(!$Window){
 $processes=@(Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowHandle -ne 0} | Where-Object {
  $candidate=Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)"
  $candidate.ExecutablePath -eq 'C:\Program Files\Google\Chrome\Application\chrome.exe' -and $candidate.CommandLine -notmatch '--user-data-dir|--incognito|--guest|--remote-debugging'
 })
 if($processes.Count -ne 1){throw '请保留一个可识别的日常Chrome窗口；未新开浏览器或切换配置'}
 $Window=[long]$processes[0].MainWindowHandle
}elseif(!$ExpectedProcessId -or !$ExpectedProcessStarted){throw '缺少日常Chrome原进程绑定，未操作'}
[uint32]$owner=0
[void][JmNativeChrome]::GetWindowThreadProcessId([IntPtr]$Window,[ref]$owner)
if(!$owner){throw '原日常Chrome窗口已关闭，未操作'}
$process=Get-Process -Id $owner -ErrorAction Stop
$info=Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
if($process.ProcessName -ne 'chrome' -or $info.ExecutablePath -ne 'C:\Program Files\Google\Chrome\Application\chrome.exe' -or $info.CommandLine -match '--user-data-dir|--incognito|--guest|--remote-debugging'){throw '当前窗口不是已确认的日常Chrome，未操作'}
$processStarted=$process.StartTime.ToUniversalTime().Ticks.ToString()
if($ExpectedProcessId -and ($owner -ne $ExpectedProcessId -or $processStarted -cne $ExpectedProcessStarted)){
 throw '原日常Chrome进程已变化，未接管其他窗口'
}
function Result($value){
 $value.window=$Window;$value.process_id=$owner;$value.process_started=$processStarted
 $value | ConvertTo-Json -Depth 7 -Compress
}
$h=[IntPtr]$Window;$w=[System.Windows.Automation.AutomationElement]::FromHandle($h)
$scope=[System.Windows.Automation.TreeScope]::Descendants
$d=$null
function Document {
 $condition=[System.Windows.Automation.AndCondition]::new(
  [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document),
  [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'RootWebArea'))
 $page=$w.FindFirst($scope,$condition)
 if(!$page){throw '网页主内容区域尚未就绪，未读取其他界面'}
 return $page
}
function CurrentUrl {
 $document=Document
 try{return $document.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value}catch{
  $address=$w.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'地址和搜索栏'))
  $value=$address.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
  if($document.Current.Name -in @('新标签页','New Tab') -and [string]::IsNullOrWhiteSpace($value)){return 'chrome://newtab/'}
  throw '当前网页网址无法核验，未导航或输入'
 }
}
function Focus {
 if(![JmNativeChrome]::Activate($h)){throw '日常Chrome不在可交互前台，未操作'}
}
function Guard {
 if(!$q.expected_url){throw '缺少原始页面网址，未操作'}
 Focus;$url=CurrentUrl
 if(([uri]$url).GetLeftPart([UriPartial]::Path) -cne ([uri]$q.expected_url).GetLeftPart([UriPartial]::Path)){throw '目标标签已变化，未操作'}
}
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
if($q.tab_key){
 $items=$w.FindAll($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem))
 # Chromium UIA can expose the same RuntimeId repeatedly in FindAll.
 # A RuntimeId identifies one element; repeated references are not new tabs.
 $owned=@($items|Where-Object {($_.GetRuntimeId() -join ',') -eq $q.tab_key}|Select-Object -First 1)
 if($owned.Count -ne 1){throw '本任务原始标签已关闭，未接管其他页面'}
 $owned[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
}
$script:seen=[System.Collections.Generic.HashSet[string]]::new()
$script:nodes=[System.Collections.Generic.List[object]]::new()
$script:elements=@{}
$script:stopAtDocument=$false
function Walk($e,$depth,$parent=''){
 if($depth -gt 45 -or $script:nodes.Count -ge 3500){return}
 $key=$e.GetRuntimeId() -join ','
 if(!$script:seen.Add($key)){return}
 $c=$e.Current;$type=$c.ControlType.ProgrammaticName.Replace('ControlType.','')
 if($script:stopAtDocument -and $type -eq 'Document'){return}
 if($c.Name -or $c.AutomationId -or $type -in @('Edit','CheckBox','TabItem','Group')){
  $value='';$hasValue=$false;try{$value=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value;$hasValue=$true}catch{}
  $textInput=$false
  if($type -in @('Edit','Group')){try{$tp=$e.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern);$textInput=$true;if(!$hasValue){$value=$tp.DocumentRange.GetText(-1)}}catch{}}
  $selected=$null;try{$selected=$e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected}catch{}
  $checked=$null;if($type -eq 'CheckBox'){try{$checked=$e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState.ToString()}catch{}}
  $r=$c.BoundingRectangle
  $script:nodes.Add(@{key=$key;parent=$parent;type=$type;name=$c.Name;id=$c.AutomationId;value=$value;visible=!$c.IsOffscreen;enabled=$c.IsEnabled;selected=$selected;checked=$checked;focusable=$c.IsKeyboardFocusable;focused=$c.HasKeyboardFocus;text_input=$textInput;rect=@($r.Left,$r.Top,$r.Width,$r.Height)})
  $script:elements[$key]=$e
 }
 $child=$walker.GetFirstChild($e)
 while($child -and $script:nodes.Count -lt 3500){Walk $child ($depth+1) $key;$child=$walker.GetNextSibling($child)}
}
if($q.action -in @('tabs','select','new')){
 $script:stopAtDocument=$true;Walk $w 0
 if($q.action -eq 'tabs'){Result @{tabs=@($script:nodes|Where-Object {$_.type -eq 'TabItem'})};exit}
 if($q.action -eq 'select'){
  $tab=@($script:nodes|Where-Object {$_.type -eq 'TabItem' -and $_.key -eq $q.key})
  if($tab.Count -ne 1){throw '本任务的原始标签已关闭，未选择其他页面'}
  $script:elements[$q.key].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select();Focus
  Result @{selected=$q.key};exit
 }
 Focus;[System.Windows.Forms.SendKeys]::SendWait('^t');Result @{created=$true};exit
}
if($q.action -eq 'close-find'){
 Focus
 $close=$w.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'关闭查找栏'))
 if(!$close -or $close.Current.ControlType -ne [System.Windows.Automation.ControlType]::Button){throw '没有本次查找栏，未操作其他控件'}
 $close.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
 @{closed_find=$true}|ConvertTo-Json -Compress;exit
}
if($q.action -eq 'url'){Result @{url=(CurrentUrl)};exit}
if($q.action -eq 'navigate'){
 Guard
 $uri=[uri]$q.url
 if($uri.Scheme -ne 'https' -or $uri.Host -notin @('www.zhihu.com','zhuanlan.zhihu.com','juejin.cn','tieba.baidu.com') -or $uri.UserInfo){throw '网页目标不在本机社区发布范围'}
 $address=$w.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'地址和搜索栏'))
 $address.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($q.url);$address.SetFocus()
 if([JmNativeChrome]::GetForegroundWindow() -ne $h){throw '导航前焦点改变，未导航'}
 [System.Windows.Forms.SendKeys]::SendWait('{ENTER}');@{navigated=$q.url}|ConvertTo-Json -Compress;exit
}
$d=Document
if(!$d){throw '未找到日常Chrome网页内容'}
$url=CurrentUrl
if($q.action -eq 'snapshot' -and $q.expected_url -and ([uri]$url).GetLeftPart([UriPartial]::Path) -cne ([uri]$q.expected_url).GetLeftPart([UriPartial]::Path)){
 Result @{url=$url;title='';text='';nodes=@()};exit
}
if($q.action -ne 'snapshot'){Guard}
Walk $d 0
if($q.action -eq 'snapshot'){
 $text=$d.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1)
 Result @{url=$url;title=$d.Current.Name;text=$text;nodes=@($script:nodes.ToArray())};exit
}
if($q.action -eq 'keys'){Guard;if($q.text -eq '^{HOME}'){$d.SetFocus();Guard};[System.Windows.Forms.SendKeys]::SendWait($q.text);@{key_sent=$true}|ConvertTo-Json -Compress;exit}
if($q.action -eq 'read-more'){
 Guard;$uri=[uri](CurrentUrl)
 if(!(($uri.Host -eq 'tieba.baidu.com' -and $uri.AbsolutePath -eq '/f') -or ($uri.Host -eq 'juejin.cn' -and $uri.AbsolutePath -eq '/ai') -or ($uri.Host -eq 'www.zhihu.com' -and $uri.AbsolutePath -eq '/search'))){throw '只允许滚动已核对的公共列表'}
 $d.SetFocus();Guard
 [System.Windows.Forms.SendKeys]::SendWait('{PGDN}');Result @{scrolled=$true};exit
}
if($q.action -eq 'find'){
 Guard
 if(!$q.text -or $q.text.Length -gt 100){throw '查找文字无效，未操作'}
 [System.Windows.Forms.SendKeys]::SendWait('^f')
 $find=$w.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'查找'))
 if(!$find -or $find.Current.ControlType -ne [System.Windows.Automation.ControlType]::Edit){throw 'Chrome查找输入框未核对，未输入'}
 $find.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($q.text);$find.SetFocus()
 Focus;[System.Windows.Forms.SendKeys]::SendWait('{ENTER}');[System.Windows.Forms.SendKeys]::SendWait('{ESC}')
 Guard
 @{found_text=$q.text}|ConvertTo-Json -Compress;exit
}
if($q.action -notin @('click','paste','focus-copy','focus-paste','focus-clear','checkbox','selected')){throw '未知本机动作'}
$e=$script:elements[$q.key]
if($q.action -in @('checkbox','selected')){
 if(!$e -or $e.Current.IsOffscreen){throw '选中状态控件不在可见区域，未操作'}
 if($q.action -eq 'checkbox'){
  try{$state=$e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState.ToString();@{checked=($state -eq 'On');method='native_toggle'}|ConvertTo-Json -Compress;exit}catch{}
 }else{
  try{$state=$e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected;@{selected=$state;method='native_selection'}|ConvertTo-Json -Compress;exit}catch{}
 }
 $r=$e.Current.BoundingRectangle
 if($r.Height -lt 12 -or $r.Height -gt 65 -or $r.Width -lt 15 -or $r.Width -gt 500){throw '选中状态样式不在已验证范围，未操作'}
 $width=if($q.action -eq 'checkbox'){[int][Math]::Min($r.Width,$r.Height)}else{[int]$r.Width}
 $height=[int]$r.Height
 $point=[JmNativeChrome+Point]::new();$point.x=[int]($r.Left+$width/2);$point.y=[int]($r.Top+$height/2)
 Guard
 if([JmNativeChrome]::GetAncestor([JmNativeChrome]::WindowFromPoint($point),2) -ne $h){throw '选中状态控件被遮挡，未操作'}
 $dr=$d.Current.BoundingRectangle
 [void][JmNativeChrome]::SetCursorPos([int]($dr.Left+10),[int]($dr.Top+10));Start-Sleep -Milliseconds 60
 Add-Type -AssemblyName System.Drawing
 $bitmap=[System.Drawing.Bitmap]::new($width,$height);$graphics=[System.Drawing.Graphics]::FromImage($bitmap)
 try{
  $graphics.CopyFromScreen([int]$r.Left,[int]$r.Top,0,0,$bitmap.Size)
  $blue=0;$light=0;$total=$width*$height
  for($x=0;$x -lt $width;$x++){for($y=0;$y -lt $height;$y++){
   $color=$bitmap.GetPixel($x,$y)
   if($color.B -gt 160 -and ($color.B-$color.R) -gt 65 -and $color.G -gt 65 -and $color.G -lt 215){$blue++}
   if($color.R -gt 220 -and $color.G -gt 220 -and $color.B -gt 220){$light++}
  }}
  $threshold=if($q.action -eq 'checkbox'){0.10}else{0.02}
  $on=($blue/$total) -gt $threshold
  if(!$on -and ($light/$total) -lt 0.5){throw '选中状态无法从当前样式确认，未操作'}
  Guard
  if($q.action -eq 'checkbox'){@{checked=$on;method='visible_color';blue_ratio=($blue/$total)}|ConvertTo-Json -Compress}
  else{@{selected=$on;method='visible_color';blue_ratio=($blue/$total)}|ConvertTo-Json -Compress}
 }finally{$graphics.Dispose();$bitmap.Dispose()}
 exit
}
if($q.action -in @('focus-copy','focus-paste','focus-clear')){
 if(!$e -or $e.Current.ControlType -notin @([System.Windows.Automation.ControlType]::Edit,[System.Windows.Automation.ControlType]::Group) -or !$e.Current.IsKeyboardFocusable -or !$e.Current.IsEnabled){throw '原生文字输入框不可聚焦，未操作'}
 Guard;$e.SetFocus()
 for($i=0;$i -lt 10;$i++){
  if(([System.Windows.Automation.AutomationElement]::FocusedElement.GetRuntimeId() -join ',') -eq $q.key){break}
  Start-Sleep -Milliseconds 20
 }
 if(([System.Windows.Automation.AutomationElement]::FocusedElement.GetRuntimeId() -join ',') -ne $q.key){throw '文字输入焦点无法核验，未输入'}
 if($q.action -eq 'focus-paste'){
  if(!$q.text){throw '正文为空，未输入'}
  [System.Windows.Forms.Clipboard]::SetText($q.text);Guard
  [System.Windows.Forms.SendKeys]::SendWait('^a');[System.Windows.Forms.SendKeys]::SendWait('^v')
 }
 Guard;[System.Windows.Forms.Clipboard]::Clear();[System.Windows.Forms.SendKeys]::SendWait('^a');[System.Windows.Forms.SendKeys]::SendWait('^c')
 $copied=[System.Windows.Forms.Clipboard]::GetText()
 if($q.action -eq 'focus-clear'){
  if($copied -cne $q.text){throw '临时输入内容改变，已保留，未清空'}
  Guard
  if(([System.Windows.Automation.AutomationElement]::FocusedElement.GetRuntimeId() -join ',') -ne $q.key){throw '临时输入焦点变化，未清空'}
  [System.Windows.Forms.SendKeys]::SendWait('{BACKSPACE}')
  @{cleared=$true}|ConvertTo-Json -Compress;exit
 }
 $html=[System.Windows.Forms.Clipboard]::GetText([System.Windows.Forms.TextDataFormat]::Html)
 @{value=$copied;html=$html;action=$q.action}|ConvertTo-Json -Compress;exit
}
if(!$e -or $e.Current.IsOffscreen -or !$e.Current.IsEnabled){throw '目标控件消失、不可见或不可用，未操作'}
$r=$e.Current.BoundingRectangle
$x=[int]($r.Left+$r.Width/2);$y=[int]($r.Top+$r.Height/2)
[void][JmNativeChrome]::SetCursorPos($x,$y);Guard
$point=[JmNativeChrome+Point]::new();$point.x=$x;$point.y=$y
if([JmNativeChrome]::GetAncestor([JmNativeChrome]::WindowFromPoint($point),2) -ne $h){throw '其他窗口遮挡目标控件，未点击'}
[JmNativeChrome]::mouse_event(2,0,0,0,[UIntPtr]::Zero);[JmNativeChrome]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
if($q.action -eq 'paste'){
 if(!$q.text){throw '正文为空，未输入'}
 [System.Windows.Forms.Clipboard]::SetText($q.text);Guard
 [System.Windows.Forms.SendKeys]::SendWait('^a');[System.Windows.Forms.SendKeys]::SendWait('^v')
}
@{action=$q.action;completed=$true}|ConvertTo-Json -Compress
