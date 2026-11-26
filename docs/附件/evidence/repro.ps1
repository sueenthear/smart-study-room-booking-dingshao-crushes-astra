<#
    证据复现脚本：越权 / 并发 / 状态回退 / 硬编码口令
    用法：powershell -ExecutionPolicy Bypass -File .\repro.ps1 -Base http://127.0.0.1:8000
    说明：脚本只发请求、只打印结果，不做断言判死；结论请对照 02 的 A.6 表人工勾。
#>
param(
    [string]$Base       = "http://127.0.0.1:8000",
    [string]$StudentNo  = "2023001",
    [string]$Password   = "123456aa",
    [int]$UserId        = 1,
    [int]$RoomA         = 1,
    [int]$RoomB         = 2,
    [string]$StartAt    = "2026-11-05 14:00",
    [string]$EndAt      = "2026-11-05 16:00",
    [int]$BookingId     = 1
)

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"
$rows = @()

function Row($id, $what, $expect, $got, $verdict) {
    $script:rows += [pscustomobject]@{ 编号 = $id; 场景 = $what; 预期 = $expect; 实测 = $got; 判定 = $verdict }
    Write-Host ("[{0}] {1}" -f $id, $what) -ForegroundColor Cyan
    Write-Host ("      预期：{0}" -f $expect)
    Write-Host ("      实测：{0}" -f $got)
}

function Send($method, $url, $body) {
    $p = @{ Uri = $url; Method = $method; UseBasicParsing = $true; TimeoutSec = 15 }
    if ($body) {
        $p.Body        = ($body | ConvertTo-Json -Compress)
        $p.ContentType = "application/json"
    }
    try {
        $r = Invoke-WebRequest @p
        return @{ code = [int]$r.StatusCode; text = $r.Content }
    } catch {
        $code = 0; $text = $_.Exception.Message
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
            try { $text = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch {}
        }
        return @{ code = $code; text = $text }
    }
}

Write-Host "`n=== 0. 连通性 ===" -ForegroundColor Yellow
$h = Send "GET" "$Base/api/overview" $null
Write-Host ("GET /api/overview -> {0}" -f $h.code)
if ($h.code -ne 200) { Write-Host "服务没起来或端口不对，后面的步骤没有意义。" -ForegroundColor Red; return }

Write-Host "`n=== E1. 管理员口令硬编码（V-01） ===" -ForegroundColor Yellow
$r1 = Send "POST" "$Base/api/auth/login" @{ role = "admin"; account = "admin"; password = "admin123456" }
Row "E1" "用源码里的 admin/admin123456 登录" "应拒绝（凭据不应写在代码里）" ("HTTP {0} {1}" -f $r1.code, $r1.text) $(if ($r1.code -eq 200) { "FAIL：硬编码口令可直接登录" } else { "PASS" })

Write-Host "`n=== E2. 无身份越权改他人预约（V-01） ===" -ForegroundColor Yellow
$r2 = Send "PATCH" "$Base/api/bookings/$BookingId/status?status=cancelled" $null
Row "E2" "不带任何凭证把预约 $BookingId 改成 cancelled" "应返回 401/403" ("HTTP {0} {1}" -f $r2.code, $r2.text) $(if ($r2.code -eq 200) { "FAIL：越权成功" } else { "PASS" })

Write-Host "`n=== E3. 同一学生同一时段两座位（BR-01 未实现，V-02） ===" -ForegroundColor Yellow
$b1 = @{ user_id = $UserId; room_id = $RoomA; start_at = $StartAt; end_at = $EndAt }
$b2 = @{ user_id = $UserId; room_id = $RoomB; start_at = $StartAt; end_at = $EndAt }
$r3a = Send "POST" "$Base/api/bookings" $b1
$r3b = Send "POST" "$Base/api/bookings" $b2
Row "E3" "同一 user_id 在 $StartAt—$EndAt 订两个座位" "第二条应 409（BR-01）" ("第一条 HTTP {0}；第二条 HTTP {1}" -f $r3a.code, $r3b.code) $(if ($r3b.code -eq 409) { "PASS" } else { "FAIL：同人重叠未被拦截" })

Write-Host "`n=== E4. 同一座位并发双提交（V-02） ===" -ForegroundColor Yellow
$t0 = (Get-Date).AddSeconds(6)
$jobScript = {
    param($base, $body, $t0)
    while ((Get-Date) -lt $t0) { Start-Sleep -Milliseconds 20 }
    try {
        $r = Invoke-WebRequest -Uri "$base/api/bookings" -Method POST -ContentType "application/json" `
             -Body ($body | ConvertTo-Json -Compress) -UseBasicParsing -TimeoutSec 15
        return [int]$r.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode } else { return 0 }
    }
}
$bc = @{ user_id = $UserId; room_id = $RoomA; start_at = $StartAt; end_at = $EndAt }
$j1 = Start-Job -ScriptBlock $jobScript -ArgumentList $Base, $bc, $t0
$j2 = Start-Job -ScriptBlock $jobScript -ArgumentList $Base, $bc, $t0
$null = Wait-Job $j1, $j2 -Timeout 40
$c1 = Receive-Job $j1; $c2 = Receive-Job $j2
Remove-Job $j1, $j2 -Force
Row "E4" "两个请求在同一时刻抢同一座位同一时段" "应一条 200、一条 409" ("HTTP {0} / HTTP {1}" -f $c1, $c2) $(if (($c1 -eq 200 -and $c2 -eq 409) -or ($c1 -eq 409 -and $c2 -eq 200)) { "PASS" } elseif ($c1 -eq 200 -and $c2 -eq 200) { "FAIL：并发穿透，产生两条有效预约" } else { "需人工判读" })

Write-Host "`n=== E5. 状态机回退（V-04，链接 PV-03） ===" -ForegroundColor Yellow
$s1 = Send "PATCH" "$Base/api/bookings/$BookingId/status?status=completed" $null
$s2 = Send "PATCH" "$Base/api/bookings/$BookingId/status?status=booked" $null
Row "E5" "已完成 -> 已预约（非法迁移 ST-08）" "第二步应 400/409 拒绝" ("第一步 HTTP {0}；第二步 HTTP {1}" -f $s1.code, $s2.code) $(if ($s2.code -eq 200) { "FAIL：非法迁移被接受" } else { "PASS" })

Write-Host "`n=== 汇总 ===" -ForegroundColor Yellow
$rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
Write-Host "把上面的表连同时间戳存到 results\<日期>_<场景>.txt，并在 02 的 A.6 表里引用文件名。" -ForegroundColor Green
Write-Host "信用分与口令明文两项用 db_checks.sql 核对（Q6、Q7）。" -ForegroundColor Green
