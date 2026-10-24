$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $PSScriptRoot
$assetDir = Join-Path $projectRoot "assets"
$iconPath = Join-Path $assetDir "banwutong-symbol.ico"
$previewPath = Join-Path $assetDir "banwutong-preview.png"
New-Item -ItemType Directory -Path $assetDir -Force | Out-Null

function New-RoundedRectanglePath(
  [System.Drawing.RectangleF]$rectangle,
  [float]$radius
) {
  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $diameter = $radius * 2
  $arc = New-Object System.Drawing.RectangleF(
    $rectangle.X,
    $rectangle.Y,
    $diameter,
    $diameter
  )
  $path.AddArc($arc, 180, 90)
  $arc.X = $rectangle.Right - $diameter
  $path.AddArc($arc, 270, 90)
  $arc.Y = $rectangle.Bottom - $diameter
  $path.AddArc($arc, 0, 90)
  $arc.X = $rectangle.X
  $path.AddArc($arc, 90, 90)
  $path.CloseFigure()
  return $path
}

function New-MasterBitmap([int]$size) {
  $bitmap = New-Object System.Drawing.Bitmap(
    $size,
    $size,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
  )
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
  $graphics.Clear([System.Drawing.Color]::Transparent)

  $outer = New-Object System.Drawing.RectangleF(8, 8, 240, 240)
  $outerPath = New-RoundedRectanglePath $outer 58
  $gradient = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    $outer,
    [System.Drawing.ColorTranslator]::FromHtml("#1D5643"),
    [System.Drawing.ColorTranslator]::FromHtml("#09271F"),
    55
  )
  $graphics.FillPath($gradient, $outerPath)

  $borderPen = New-Object System.Drawing.Pen(
    [System.Drawing.ColorTranslator]::FromHtml("#C8A65D"),
    2.2
  )
  $inner = New-Object System.Drawing.RectangleF(15, 15, 226, 226)
  $innerPath = New-RoundedRectanglePath $inner 52
  $graphics.DrawPath($borderPen, $innerPath)

  $signalPen = New-Object System.Drawing.Pen(
    [System.Drawing.ColorTranslator]::FromHtml("#F7F1E2"),
    17
  )
  $signalPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
  $signalPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
  $signalPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round

  $centerX = 103
  $centerY = 128
  foreach ($radius in @(29, 54, 79)) {
    $diameter = $radius * 2
    $arcRect = New-Object System.Drawing.RectangleF(
      ($centerX - $radius),
      ($centerY - $radius),
      $diameter,
      $diameter
    )
    $graphics.DrawArc($signalPen, $arcRect, 90, 180)
  }

  $dotPen = New-Object System.Drawing.Pen(
    [System.Drawing.ColorTranslator]::FromHtml("#F7F1E2"),
    5
  )
  $dotBrush = New-Object System.Drawing.SolidBrush(
    [System.Drawing.ColorTranslator]::FromHtml("#E36E42")
  )
  $graphics.FillEllipse($dotBrush, 174, 105, 46, 46)
  $graphics.DrawEllipse($dotPen, 174, 105, 46, 46)

  $graphics.Dispose()
  return $bitmap
}

function New-ScaledPngBytes(
  [System.Drawing.Bitmap]$source,
  [int]$size
) {
  $bitmap = New-Object System.Drawing.Bitmap(
    $size,
    $size,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
  )
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.Clear([System.Drawing.Color]::Transparent)
  $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
  $graphics.DrawImage($source, 0, 0, $size, $size)
  $graphics.Dispose()

  $stream = New-Object System.IO.MemoryStream
  $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
  $bytes = $stream.ToArray()
  $stream.Dispose()
  $bitmap.Dispose()
  return ,$bytes
}

$master = New-MasterBitmap 256
$master.Save($previewPath, [System.Drawing.Imaging.ImageFormat]::Png)

$sizes = @(16, 24, 32, 48, 64, 128, 256)
$frames = @()
foreach ($size in $sizes) {
  $frames += ,(New-ScaledPngBytes $master $size)
}

$file = New-Object System.IO.FileStream(
  $iconPath,
  [System.IO.FileMode]::Create,
  [System.IO.FileAccess]::Write
)
$writer = New-Object System.IO.BinaryWriter($file)
$writer.Write([UInt16]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]$frames.Count)

$offset = 6 + (16 * $frames.Count)
for ($index = 0; $index -lt $frames.Count; $index++) {
  $size = $sizes[$index]
  $frame = $frames[$index]
  $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
  $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
  $writer.Write([byte]0)
  $writer.Write([byte]0)
  $writer.Write([UInt16]1)
  $writer.Write([UInt16]32)
  $writer.Write([UInt32]$frame.Length)
  $writer.Write([UInt32]$offset)
  $offset += $frame.Length
}

foreach ($frame in $frames) {
  $writer.Write($frame)
}

$writer.Dispose()
$file.Dispose()
$master.Dispose()

Write-Host "Created $iconPath"
Write-Host "Created $previewPath"
