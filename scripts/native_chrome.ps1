param([long]$Window=0)
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$q=[Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type 'using System; using System.Runtime.InteropServices; public static class JmNativeChrome { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e); [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(Point p); [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h,uint f); [StructLayout(LayoutKind.Sequential)] public struct Point { public int x; public int y; } }'
if(!$Window){
 $processes=@(Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowHandle -ne 0})
 if($processes.Count -ne 1){throw '请保留一个可识别的日常Chrome窗口；未新开浏览器或切换配置'}
 $process=$processes[0]
 $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
 if($info.ExecutablePath -ne 'C:\Program Files\Google\Chrome\Application\chrome.exe' -or $info.CommandLine -match '--user-data-dir|--incognito|--remote-debugging-port'){throw '当前窗口不是已确认的日常Chrome，未操作'}
 $Window=[long]$process.MainWindowHandle
}
$h=[IntPtr]$Window;$w=[System.Windows.Automation.AutomationElement]::FromHandle($h)
$scope=[System.Windows.Automation.TreeScope]::Descendants
$d=$null
function Document { $w.FindFirst($scope,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document)) }
function CurrentUrl { (Document).GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value }
function Focus {
 [void][JmNativeChrome]::SetForegroundWindow($h)
 if([JmNativeChrome]::GetForegroundWindow() -ne $h){throw '日常Chrome不在前台，未操作'}
}
function Guard {
 if(!$q.expected_url){throw '缺少原始页面网址，未操作'}
 Focus;$url=CurrentUrl
 if(([uri]$url).GetLeftPart([UriPartial]::Path) -cne ([uri]$q.expected_url).GetLeftPart([UriPartial]::Path)){throw '目标标签已变化，未操作'}
}
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
$script:seen=[System.Collections.Generic.HashSet[string]]::new()
$script:nodes=[System.Collections.Generic.List[object]]::new()
$script:elements=@{}
$script:stopAtDocument=$false
function Walk($e,$depth){
 if($depth -gt 45 -or $script:nodes.Count -ge 3500){return}
 $key=$e.GetRuntimeId() -join ','
 if(!$script:seen.Add($key)){return}
 $c=$e.Current;$type=$c.ControlType.ProgrammaticName.Replace('ControlType.','')
 if($script:stopAtDocument -and $type -eq 'Document'){return}
 if($c.Name -or $c.AutomationId -or $type -in @('Edit','CheckBox','TabItem')){
  $value='';try{$value=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value}catch{}
  if($type -eq 'Edit'){try{$value=$e.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1)}catch{}}
  $selected=$false;if($type -eq 'TabItem'){try{$selected=$e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected}catch{}}
  $checked=$null;if($type -eq 'CheckBox'){try{$checked=$e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState.ToString()}catch{}}
  $script:nodes.Add(@{key=$key;type=$type;name=$c.Name;id=$c.AutomationId;value=$value;visible=!$c.IsOffscreen;enabled=$c.IsEnabled;selected=$selected;checked=$checked})
  $script:elements[$key]=$e
 }
 $child=$walker.GetFirstChild($e)
 while($child -and $script:nodes.Count -lt 3500){Walk $child ($depth+1);$child=$walker.GetNextSibling($child)}
}
if($q.action -in @('tabs','select','new')){
 $script:stopAtDocument=$true;Walk $w 0
 if($q.action -eq 'tabs'){@{tabs=@($script:nodes|Where-Object {$_.type -eq 'TabItem'});window=$Window}|ConvertTo-Json -Depth 6 -Compress;exit}
 if($q.action -eq 'select'){
  $tab=@($script:nodes|Where-Object {$_.type -eq 'TabItem' -and $_.key -eq $q.key})
  if($tab.Count -ne 1){throw '本任务的原始标签已关闭，未选择其他页面'}
  $script:elements[$q.key].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select();Focus
  @{selected=$q.key;window=$Window}|ConvertTo-Json -Compress;exit
 }
 Focus;[System.Windows.Forms.SendKeys]::SendWait('^t');@{created=$true;window=$Window}|ConvertTo-Json -Compress;exit
}
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
 @{url=$url;title='';text='';nodes=@();window=$Window}|ConvertTo-Json -Compress;exit
}
if($q.action -ne 'snapshot'){Guard}
Walk $d 0
if($q.action -eq 'snapshot'){
 $text=$d.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1)
 @{url=$url;title=$d.Current.Name;text=$text;nodes=@($script:nodes.ToArray());window=$Window}|ConvertTo-Json -Depth 7 -Compress;exit
}
if($q.action -eq 'keys'){Guard;[System.Windows.Forms.SendKeys]::SendWait($q.text);@{key_sent=$true}|ConvertTo-Json -Compress;exit}
if($q.action -notin @('click','paste')){throw '未知本机动作'}
$e=$script:elements[$q.key]
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
