# Hub Design System - WPF / PowerShell Edition

Version: 1.2 | Last reviewed: 2026-10-06 | Status: current | Scope: WPF / PowerShell 5.1

Official "Hub" standard for PowerShell 5.1 WPF GUI tools. Derived from the owning team Hub web design system. Dark near-black surfaces, a single orange accent (#E06420), borders not shadows, uppercase tracked micro-labels.

This document is ASCII-only. Every XAML block is valid for `XamlReader.Parse`/`XamlReader.Load` on .NET Framework / PowerShell 5.1 (no x:Class, no code-behind, no compiled MarkupExtensions, no design-time attributes). Fonts are Segoe UI (all UI text) and Consolas (monospace: versions, logs, paths, IDs). IBM Plex Sans/Mono are NOT used.

---

## 0. How to consume this in PowerShell 5.1

Pattern for loading any XAML in this document. All styles in Sections 1, 2, and 4 are designed to live inside one `<Window.Resources>` (or a merged `ResourceDictionary`) so every `x:Key` and `{StaticResource}` reference resolves.

```powershell
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

[xml]$xaml = Get-Content -Path "$PSScriptRoot\MainWindow.xaml" -Raw
$reader   = New-Object System.Xml.XmlNodeReader $xaml
$window   = [Windows.Markup.XamlReader]::Load($reader)

# Find named elements:
$btnRun = $window.FindName('BtnRun')

$window.ShowDialog() | Out-Null
```

Rules that keep this from silently breaking:

- Save the `.ps1` and any inline here-string XAML as ANSI/ASCII. Any byte > 127 breaks parsing when launched `-WindowStyle Hidden`. This whole document is ASCII; keep it that way.
- In XAML, escape `&` as `&amp;`, `<` as `&lt;`, `>` as `&gt;`. For literal newlines inside an attribute value (e.g. multi-line log text) use the ASCII entity `&#x0a;` - never a literal non-ASCII line separator.
- The root element must declare both namespaces:
  `xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"`
  `xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"`
- Do not use `x:Class`. Wire events in PowerShell with `$element.Add_Click({ ... })`.

---

## 1. Color Tokens

Single source of truth. Backgrounds are near-black; one orange accent used sparingly. Tints are concrete WPF colors.

### Tint approach (chosen, stated once)

Tailwind opacity tints are converted to **explicit #AARRGGBB hex** (8-digit: alpha first). WPF brushes accept `#AARRGGBB` directly, so `rgba(224,100,32,0.10)` becomes `#1AE06420` (alpha 0.10 * 255 = 25.5 -> 0x1A). This keeps the "tint over near-black" look honest (the alpha actually composites over whatever is behind it) and is the most maintainable. Opaque colors always carry an explicit `#FF` alpha so there is no ambiguity.

### Alpha byte reference (derive any tint without re-reading prose)

Multiply the opacity by 255 and round. Use these canonical bytes; the 0.30 case is pinned to `0x4D` (153 * 0.30 = 45.9, rounded up) and used consistently everywhere in this document:

| Opacity | Alpha byte |
|---|---|
| 0.05 | 0D |
| 0.08 | 14 |
| 0.10 | 1A |
| 0.15 | 26 |
| 0.20 | 33 |
| 0.25 | 40 |
| 0.30 | 4D |
| 0.40 | 66 |
| 0.50 | 80 |
| 0.60 | 99 |

### Base tokens

| Token | WPF value | Role |
|---|---|---|
| Hub.Bg | #FF0C0C0C | Window / body background (near-black) |
| Hub.Panel | #FF141414 | Sidebar, card / panel surface |
| Hub.Panel2 | #FF1C1C1C | Elevated surface, hover background |
| Hub.Border | #FF2A2A2A | Default border, dividers |
| Hub.BorderSoft | #FF202020 | Soft row dividers (DataGrid horizontal lines) |
| Hub.Text | #FFF2EDE8 | Primary text (warm white) |
| Hub.Muted | #FF6E6E6E | Secondary text, labels, placeholders |
| Hub.Accent | #FFE06420 | brand orange: primary action, active, focus |
| Hub.AccentHover | #FFC85518 | Accent hover / pressed |
| Hub.Code | #FF0A0A0A | Deepest black: code / log surface |
| Hub.White | #FFFFFFFF | Text on filled accent button |

### Semantic tokens

| Token | WPF value | Role |
|---|---|---|
| Hub.Success | #FF22C55E | Success text / dot |
| Hub.Error | #FFEF4444 | Error text / dot |
| Hub.Warning | #FFF59E0B | Warning text / dot |
| Hub.Info | #FF3B82F6 | Info text / dot |

### Tint tokens (precomputed #AARRGGBB)

| Token | WPF value | Source | Role |
|---|---|---|---|
| Hub.Accent.05 | #0DE06420 | accent 5% | faint accent wash |
| Hub.Accent.08 | #14E06420 | accent 8% | faint accent tint (not used for selection; selection is neutral) |
| Hub.Accent.10 | #1AE06420 | accent 10% | accent tint bg (ds-accent-dim) |
| Hub.Accent.15 | #26E06420 | accent 15% | hover tint |
| Hub.Accent.20 | #33E06420 | accent 20% | avatar circle bg |
| Hub.Accent.30 | #4DE06420 | accent 30% | avatar circle border |
| Hub.Accent.40 | #66E06420 | accent 40% | **hover-card border**, focus ring |
| Hub.Success.10 | #1A22C55E | success 10% | success badge bg |
| Hub.Success.25 | #4022C55E | success 25% | success badge border |
| Hub.Error.10 | #1AEF4444 | error 10% | error badge / danger button bg |
| Hub.Error.20 | #33EF4444 | error 20% | danger button hover bg |
| Hub.Error.25 | #40EF4444 | error 25% | error badge border |
| Hub.Error.30 | #4DEF4444 | error 30% | danger button border |
| Hub.Warning.10 | #1AF59E0B | warning 10% | warning badge bg |
| Hub.Warning.25 | #40F59E0B | warning 25% | warning badge border |
| Hub.Info.10 | #1A3B82F6 | info 10% | info / idle badge bg |
| Hub.Info.25 | #403B82F6 | info 25% | info / idle badge border |

### Resource dictionary block (paste into Window.Resources)

```xml
<!-- ============ COLOR TOKENS ============ -->
<SolidColorBrush x:Key="Hub.Bg"          Color="#FF0C0C0C"/>
<SolidColorBrush x:Key="Hub.Panel"       Color="#FF141414"/>
<SolidColorBrush x:Key="Hub.Panel2"      Color="#FF1C1C1C"/>
<SolidColorBrush x:Key="Hub.Border"      Color="#FF2A2A2A"/>
<SolidColorBrush x:Key="Hub.BorderSoft"  Color="#FF202020"/>
<SolidColorBrush x:Key="Hub.Text"        Color="#FFF2EDE8"/>
<SolidColorBrush x:Key="Hub.Muted"       Color="#FF6E6E6E"/>
<SolidColorBrush x:Key="Hub.Accent"      Color="#FFE06420"/>
<SolidColorBrush x:Key="Hub.AccentHover" Color="#FFC85518"/>
<SolidColorBrush x:Key="Hub.Code"        Color="#FF0A0A0A"/>
<SolidColorBrush x:Key="Hub.White"       Color="#FFFFFFFF"/>

<SolidColorBrush x:Key="Hub.Success"     Color="#FF22C55E"/>
<SolidColorBrush x:Key="Hub.Error"       Color="#FFEF4444"/>
<SolidColorBrush x:Key="Hub.Warning"     Color="#FFF59E0B"/>
<SolidColorBrush x:Key="Hub.Info"        Color="#FF3B82F6"/>

<SolidColorBrush x:Key="Hub.Accent.05"   Color="#0DE06420"/>
<SolidColorBrush x:Key="Hub.Accent.08"   Color="#14E06420"/>
<SolidColorBrush x:Key="Hub.Accent.10"   Color="#1AE06420"/>
<SolidColorBrush x:Key="Hub.Accent.15"   Color="#26E06420"/>
<SolidColorBrush x:Key="Hub.Accent.20"   Color="#33E06420"/>
<SolidColorBrush x:Key="Hub.Accent.30"   Color="#4DE06420"/>
<SolidColorBrush x:Key="Hub.Accent.40"   Color="#66E06420"/>

<SolidColorBrush x:Key="Hub.Success.10"  Color="#1A22C55E"/>
<SolidColorBrush x:Key="Hub.Success.25"  Color="#4022C55E"/>
<SolidColorBrush x:Key="Hub.Error.10"    Color="#1AEF4444"/>
<SolidColorBrush x:Key="Hub.Error.20"    Color="#33EF4444"/>
<SolidColorBrush x:Key="Hub.Error.25"    Color="#40EF4444"/>
<SolidColorBrush x:Key="Hub.Error.30"    Color="#4DEF4444"/>
<SolidColorBrush x:Key="Hub.Warning.10"  Color="#1AF59E0B"/>
<SolidColorBrush x:Key="Hub.Warning.25"  Color="#40F59E0B"/>
<SolidColorBrush x:Key="Hub.Info.10"     Color="#1A3B82F6"/>
<SolidColorBrush x:Key="Hub.Info.25"     Color="#403B82F6"/>
```

---

## 2. Typography

All UI text is **Segoe UI**. Monospace is **Consolas**. Nothing else. WPF uses device-independent units (1/96 in); the hub's px values map 1:1 to WPF `FontSize`.

### Size + weight scale

| Hub name | px / FontSize | FontWeight | Where |
|---|---|---|---|
| 2xs | 10 | SemiBold / Bold | micro-labels, table headers, badge text, version, metadata |
| xs | 12 | Medium | body, nav items, button text, table cells |
| sm | 14 | SemiBold | card titles, modal / panel headers |
| lg | 18 | SemiBold | section headings |
| welcome | 22 | SemiBold | welcome / page heading |
| 2xl | 24 | Bold | stat numbers, initials |

WPF FontWeight names: `Medium` (=500), `SemiBold` (=600), `Bold` (=700). Use these literal names.

### The uppercase micro-label recipe (letter-spacing in WPF)

WPF `TextBlock` has no `letter-spacing` property, and `CharacterSpacing` is not available on plain TextBlock under .NET Framework. Two supported approaches:

1. **Recommended for static labels (the standard):** pre-uppercase the text in PowerShell and rely on FontWeight + size for the "tracked" feel. This is the simplest approach that survives `XamlReader.Load` with no code-behind. The `Hub.MicroLabel` style below uses this; pass already-uppercased strings.

2. **True per-character tracking (use only when the look must be exact):** build the label in PowerShell by inserting one `Run` per character and spacing them with a margin. A `Run` has no `Margin` (it is an inline, not a `FrameworkElement`), so setting one throws. Wrap each character in an `InlineUIContainer` holding a `TextBlock` whose `Margin` carries the gap. Reserve for hero section labels.

```powershell
function Set-TrackedLabel {
    param([System.Windows.Controls.TextBlock]$Target, [string]$Text, [double]$Track = 1.2)
    $Target.Inlines.Clear()
    foreach ($ch in $Text.ToUpper().ToCharArray()) {
        $tb = New-Object System.Windows.Controls.TextBlock
        $tb.Text       = [string]$ch
        $tb.FontWeight = [System.Windows.FontWeights]::SemiBold
        $tb.Margin     = (New-Object System.Windows.Thickness(0, 0, $Track, 0))
        $Target.Inlines.Add((New-Object System.Windows.Documents.InlineUIContainer($tb)))
    }
}
```

**Standard:** use option 1 (the `Hub.MicroLabel` style) for nav, table headers, badges, and section labels - pre-uppercase the text. Reserve option 2 for hero section labels where the tracked look must be exact. Document which you used.

```xml
<!-- ============ TYPOGRAPHY ============ -->
<!-- Uppercase 10px tracked muted micro-label.
     Pre-uppercase the Text in PowerShell; spacing comes from weight+size. -->
<Style x:Key="Hub.MicroLabel" TargetType="TextBlock">
    <Setter Property="FontFamily"   Value="Segoe UI"/>
    <Setter Property="FontSize"     Value="10"/>
    <Setter Property="FontWeight"   Value="SemiBold"/>
    <Setter Property="Foreground"   Value="{StaticResource Hub.Muted}"/>
    <Setter Property="TextOptions.TextFormattingMode" Value="Display"/>
</Style>

<!-- Body text -->
<Style x:Key="Hub.Body" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="FontWeight" Value="Medium"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
</Style>

<!-- Section heading 18px -->
<Style x:Key="Hub.Heading" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="18"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
</Style>

<!-- Welcome / page title 22px -->
<Style x:Key="Hub.Title" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="22"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
</Style>

<!-- Stat number 24px bold -->
<Style x:Key="Hub.Stat" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="24"/>
    <Setter Property="FontWeight" Value="Bold"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
</Style>

<!-- Monospace: version strings, logs, paths, IDs, timestamps -->
<Style x:Key="Hub.Mono" TargetType="TextBlock">
    <Setter Property="FontFamily" Value="Consolas"/>
    <Setter Property="FontSize"   Value="10"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Muted}"/>
</Style>
```

**Where Consolas (mono) is used:** version strings, log / console output, file paths, device IDs, MAC addresses, GUIDs, timestamps, table cells holding IDs/paths, and the code/log surface (Hub.Code background). Everything else is Segoe UI.

---

## 3. Geometry & Surfaces

| Element | Corner radius |
|---|---|
| Card / panel | 12 |
| Button / input / combobox / nav item | 8 |
| Badge / pill | 4 |
| Avatar / status dot | circle (CornerRadius = half of size, or use Ellipse) |
| Small icon container | 8 |

Rules:

- **Borders define surfaces, not shadows.** Cards and panels have `BorderThickness="1"` with `Hub.Border` and NO `DropShadowEffect`. Only the primary button and toasts may carry a subtle shadow.
- **Page content padding = 24.** Sidebar nav area = 12 vertical / 8 horizontal. Card padding = 20.
- Surfaces stack by lightness: Bg (#0C0C0C) -> Panel (#141414) -> Panel2 (#1C1C1C, hover/elevated). Code/log = #0A0A0A (darker than Bg).
- One accent. Orange appears on the primary button, focus border, running badge, and the occasional category dot - nowhere else by default. Selection is neutral (Panel2 + a 1px Border hairline + Text), never an orange wash or an edge bar.

---

## 4. XAML Control Kit

Everything below is one cohesive set of `x:Key` styles. Drop the whole kit (plus the Section 1 and Section 2 blocks) into a single `<Window.Resources>`. Every `x:Key` in this document is unique - there are no duplicate or conflicting keys.

### 4a. Window

```xml
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Hub Tool"
    Width="1080" Height="720"
    MinWidth="820" MinHeight="560"
    WindowStartupLocation="CenterScreen"
    Background="#FF0C0C0C"
    Foreground="#FFF2EDE8"
    FontFamily="Segoe UI"
    FontSize="12"
    TextOptions.TextFormattingMode="Display"
    UseLayoutRounding="True"
    SnapsToDevicePixels="True">
  <Window.Resources>
    <!-- Paste: color tokens (Sec 1), typography (Sec 2), then 4b..4n below -->
  </Window.Resources>

  <!-- Root layout: fixed sidebar + content -->
  <Grid>
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="210"/>
      <ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>
    <!-- Col 0: sidebar (4b/4c)  |  Col 1: page content, Padding=24 -->
  </Grid>
</Window>
```

Sizing guidance: default 1080x720, minimums 820x560. Use `UseLayoutRounding` + `SnapsToDevicePixels` for crisp 1px borders on the dark theme. `TextFormattingMode=Display` keeps small Segoe UI text sharp.

### 4b. Sidebar container + brand header

```xml
<!-- ============ SIDEBAR ============ -->
<Style x:Key="Hub.Sidebar" TargetType="Border">
    <Setter Property="Background"          Value="{StaticResource Hub.Panel}"/>
    <Setter Property="BorderBrush"         Value="{StaticResource Hub.Border}"/>
    <Setter Property="BorderThickness"     Value="0,0,1,0"/>
</Style>
```

```xml
<!-- Sidebar usage: place in Grid column 0 -->
<Border Style="{StaticResource Hub.Sidebar}">
  <DockPanel LastChildFill="True">

    <!-- Brand header: ~56 tall, padding 16,0 -->
    <Border DockPanel.Dock="Top" Height="56" Padding="16,0"
            BorderBrush="{StaticResource Hub.Border}" BorderThickness="0,0,0,1">
      <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
        <!-- 32px logo square -->
        <Border Width="32" Height="32" CornerRadius="8"
                Background="{StaticResource Hub.Accent}">
          <TextBlock Text="O" Foreground="{StaticResource Hub.White}"
                     FontWeight="Bold" FontSize="16"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <StackPanel Margin="10,0,0,0" VerticalAlignment="Center">
          <TextBlock Text="Hub" Foreground="{StaticResource Hub.Text}"
                     FontSize="14" FontWeight="SemiBold"/>
          <TextBlock Text="TEAM NAME"
                     Style="{StaticResource Hub.MicroLabel}" Margin="0,1,0,0"/>
        </StackPanel>
      </StackPanel>
    </Border>

    <!-- Footer: user chip + version (DockPanel bottom) -->
    <Border DockPanel.Dock="Bottom" Padding="12,10"
            BorderBrush="{StaticResource Hub.Border}" BorderThickness="0,1,0,0">
      <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
        <Border Width="30" Height="30" CornerRadius="15"
                Background="{StaticResource Hub.Accent.20}"
                BorderBrush="{StaticResource Hub.Accent.30}" BorderThickness="1">
          <TextBlock Text="AB" Foreground="{StaticResource Hub.Accent}"
                     FontSize="10" FontWeight="Bold"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <StackPanel Margin="8,0,0,0" VerticalAlignment="Center">
          <TextBlock Text="Operator" Foreground="{StaticResource Hub.Text}"
                     FontSize="12" FontWeight="Medium"/>
          <TextBlock Text="v1.0.0" FontFamily="Consolas" FontSize="10"
                     Foreground="{StaticResource Hub.Muted}"/>
        </StackPanel>
      </StackPanel>
    </Border>

    <!-- Nav area fills remaining space -->
    <ListBox x:Name="Nav" Style="{StaticResource Hub.NavList}"
             Padding="8,12" ScrollViewer.HorizontalScrollBarVisibility="Disabled">
      <!-- ListBoxItems use Hub.NavItem (4c) -->
    </ListBox>

  </DockPanel>
</Border>
```

### 4c. Nav item with a raised neutral selection (no edge bar)

**Mechanism choice: `ListBox` + `ListBoxItem` ControlTemplate.** Justification: a ListBox gives single-selection semantics for free (`IsSelected` drives the active state), keyboard navigation, and a clean `ItemsSource` binding path - no manual RadioButton group wiring, no ToggleButton un-check edge cases. The selected item is a raised neutral surface: `Panel2` background, a 1px `Border` hairline all the way round and `Text` foreground at SemiBold. There is no accent bar or stripe on any edge, per rule 1 of the [Web Design System](web-ui.md#0-the-rules-non-negotiable). This is the idiomatic WPF master-nav pattern.

**Foreground inheritance trap (must follow):** do NOT set `Foreground` on the inner label `TextBlock`. The `ListBoxItem` template's `IsSelected` / `IsMouseOver` triggers set foreground on the named `Label` element; if you also hard-code `Foreground` on that TextBlock inline, the local value wins and the active/hover color is silently ignored. Let the template drive it.

```xml
<!-- ============ NAV ============ -->
<Style x:Key="Hub.NavList" TargetType="ListBox">
    <Setter Property="Background"       Value="Transparent"/>
    <Setter Property="BorderThickness"  Value="0"/>
    <Setter Property="Foreground"       Value="{StaticResource Hub.Muted}"/>
    <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
</Style>

<Style x:Key="Hub.NavItem" TargetType="ListBoxItem">
    <Setter Property="FontFamily"   Value="Segoe UI"/>
    <Setter Property="FontSize"     Value="12"/>
    <Setter Property="FontWeight"   Value="Medium"/>
    <Setter Property="Foreground"   Value="{StaticResource Hub.Muted}"/>
    <Setter Property="Margin"       Value="0,1"/>
    <Setter Property="Padding"      Value="0"/>
    <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ListBoxItem">
          <Grid>
            <!-- Raised neutral surface when selected; no edge bar -->
            <Border x:Name="Bg" CornerRadius="8" Background="Transparent"
                    BorderBrush="Transparent" BorderThickness="1" Padding="11,6">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bg" Property="Background" Value="{StaticResource Hub.Panel2}"/>
              <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
            </Trigger>
            <Trigger Property="IsSelected" Value="True">
              <Setter TargetName="Bg" Property="Background"  Value="{StaticResource Hub.Panel2}"/>
              <Setter TargetName="Bg" Property="BorderBrush" Value="{StaticResource Hub.Border}"/>
              <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
              <Setter Property="FontWeight" Value="SemiBold"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>
```

**Default usage - literal content (renders out-of-the-box).** Put the icon glyph and label directly inside each item. Note there is no `Foreground` on the label TextBlock, so the template's selection/hover triggers win:

```xml
<ListBox x:Name="Nav" Style="{StaticResource Hub.NavList}" Padding="8,12">
  <ListBoxItem Style="{StaticResource Hub.NavItem}" IsSelected="True">
    <StackPanel Orientation="Horizontal">
      <!-- 15px icon slot: draw a Path glyph; placeholder square shown here -->
      <Border Width="15" Height="15" VerticalAlignment="Center" Background="Transparent">
        <Path Stretch="Uniform" Stroke="{StaticResource Hub.Muted}" StrokeThickness="1.5"
              Data="M 2 2 L 13 2 L 13 13 L 2 13 Z"/>
      </Border>
      <TextBlock Text="Dashboard" Margin="12,0,0,0" VerticalAlignment="Center"/>
    </StackPanel>
  </ListBoxItem>
  <ListBoxItem Style="{StaticResource Hub.NavItem}">
    <StackPanel Orientation="Horizontal">
      <Border Width="15" Height="15" VerticalAlignment="Center" Background="Transparent">
        <Path Stretch="Uniform" Stroke="{StaticResource Hub.Muted}" StrokeThickness="1.5"
              Data="M 2 6 L 13 6 M 2 10 L 13 10"/>
      </Border>
      <TextBlock Text="Deployments" Margin="12,0,0,0" VerticalAlignment="Center"/>
    </StackPanel>
  </ListBoxItem>
</ListBox>
```

**ItemsSource variant (bound).** When binding a collection, set the container style and provide an `ItemTemplate` that mirrors the literal layout. Bind `Icon`/`Label` to your data objects:

```xml
<ListBox x:Name="Nav" Style="{StaticResource Hub.NavList}" Padding="8,12"
         ItemContainerStyle="{StaticResource Hub.NavItem}"
         ItemsSource="{Binding NavItems}">
  <ListBox.ItemTemplate>
    <DataTemplate>
      <StackPanel Orientation="Horizontal">
        <Border Width="15" Height="15" VerticalAlignment="Center" Background="Transparent">
          <ContentControl Content="{Binding Icon}"/>
        </Border>
        <TextBlock Text="{Binding Label}" Margin="12,0,0,0" VerticalAlignment="Center"/>
      </StackPanel>
    </DataTemplate>
  </ListBox.ItemTemplate>
</ListBox>
```

### 4d. Tool card

```xml
<!-- ============ TOOL CARD ============ -->
<Style x:Key="Hub.Card" TargetType="Border">
    <Setter Property="Background"      Value="{StaticResource Hub.Panel}"/>
    <Setter Property="BorderBrush"     Value="{StaticResource Hub.Border}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CornerRadius"    Value="12"/>
    <Setter Property="Padding"         Value="20"/>
    <Setter Property="Margin"          Value="0,0,16,16"/>
    <Style.Triggers>
      <Trigger Property="IsMouseOver" Value="True">
        <Setter Property="Background"  Value="{StaticResource Hub.Panel2}"/>
        <Setter Property="BorderBrush" Value="{StaticResource Hub.Accent.40}"/>
      </Trigger>
    </Style.Triggers>
</Style>
```

```xml
<!-- Card usage -->
<Border Style="{StaticResource Hub.Card}" Width="280">
  <StackPanel>
    <!-- 40px icon container -->
    <Border Width="40" Height="40" CornerRadius="8"
            Background="{StaticResource Hub.Panel2}"
            BorderBrush="{StaticResource Hub.Border}" BorderThickness="1">
      <TextBlock Text="O" Foreground="{StaticResource Hub.Accent}"
                 FontWeight="Bold" HorizontalAlignment="Center"
                 VerticalAlignment="Center"/>
    </Border>

    <TextBlock Text="Deployment Tool" Margin="0,14,0,4"
               FontSize="14" FontWeight="SemiBold"
               Foreground="{StaticResource Hub.Text}"/>

    <!-- 2-line description with trimming -->
    <TextBlock Text="Push packages to managed endpoints and track rollout state across rings."
               FontSize="12" Foreground="{StaticResource Hub.Muted}"
               TextWrapping="Wrap" MaxHeight="34"
               TextTrimming="CharacterEllipsis"/>

    <!-- Footer: category dot + version -->
    <StackPanel Orientation="Horizontal" Margin="0,14,0,0" VerticalAlignment="Center">
      <Ellipse Width="8" Height="8" Fill="{StaticResource Hub.Info}"
               VerticalAlignment="Center"/>
      <TextBlock Text="ENDPOINT" Margin="6,0,0,0" Style="{StaticResource Hub.MicroLabel}"
                 VerticalAlignment="Center"/>
      <TextBlock Text="v2.3.1" Margin="10,0,0,0" FontFamily="Consolas"
                 FontSize="10" Foreground="{StaticResource Hub.Muted}"
                 VerticalAlignment="Center"/>
    </StackPanel>
  </StackPanel>
</Border>
```

For a disabled card, set `Opacity="0.4"` and `IsHitTestVisible="False"` on the Border. Lay cards out in a `WrapPanel` for responsive 1/2/3-column flow (gap handled by the card `Margin`).

### 4e. Section micro-label

Defined in Section 2 as `Hub.MicroLabel`. Usage: `<TextBlock Text="RECENT ACTIVITY" Style="{StaticResource Hub.MicroLabel}"/>` - always pass already-uppercased text.

### 4f. Search TextBox with left glyph + placeholder

**Placeholder technique:** overlay a `TextBlock` inside the control template, collapsed unless the textbox text is empty. Empty-detection without code-behind uses a `Trigger` bound to the TextBox's own `Text` with `Value=""`. This is robust under `XamlReader.Load` (no converters needed).

```xml
<!-- ============ TEXTBOX (plain + search) ============ -->
<Style x:Key="Hub.TextBox" TargetType="TextBox">
    <Setter Property="FontFamily"        Value="Segoe UI"/>
    <Setter Property="FontSize"          Value="12"/>
    <Setter Property="Foreground"        Value="{StaticResource Hub.Text}"/>
    <Setter Property="CaretBrush"        Value="{StaticResource Hub.Accent}"/>
    <Setter Property="Background"        Value="{StaticResource Hub.Code}"/>
    <Setter Property="BorderBrush"       Value="{StaticResource Hub.Border}"/>
    <Setter Property="BorderThickness"   Value="1"/>
    <Setter Property="Padding"           Value="12,6"/>
    <Setter Property="Tag"               Value="Search..."/>  <!-- placeholder text -->
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TextBox">
          <Border x:Name="Bd" CornerRadius="8"
                  Background="{TemplateBinding Background}"
                  BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="{TemplateBinding BorderThickness}"
                  Padding="{TemplateBinding Padding}">
            <Grid>
              <ScrollViewer x:Name="PART_ContentHost"
                            VerticalAlignment="Center"/>
              <TextBlock x:Name="Placeholder"
                         Text="{TemplateBinding Tag}"
                         Margin="2,0,0,0"
                         VerticalAlignment="Center"
                         Foreground="{StaticResource Hub.Muted}"
                         IsHitTestVisible="False"
                         Visibility="Collapsed"/>
            </Grid>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="Text" Value="">
              <Setter TargetName="Placeholder" Property="Visibility" Value="Visible"/>
            </Trigger>
            <Trigger Property="IsKeyboardFocused" Value="True">
              <Setter TargetName="Bd" Property="BorderBrush" Value="{StaticResource Hub.Accent}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<!-- Search variant: adds left 14px glyph and indents text -->
<Style x:Key="Hub.SearchBox" TargetType="TextBox" BasedOn="{StaticResource Hub.TextBox}">
    <Setter Property="Padding" Value="32,6,12,6"/>
    <Setter Property="Tag"     Value="Search..."/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TextBox">
          <Border x:Name="Bd" CornerRadius="8"
                  Background="{TemplateBinding Background}"
                  BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="{TemplateBinding BorderThickness}">
            <Grid>
              <!-- Search glyph: magnifier drawn with Path, 14px, muted -->
              <Path Width="14" Height="14" Margin="10,0,0,0"
                    HorizontalAlignment="Left" VerticalAlignment="Center"
                    Stretch="Uniform"
                    Stroke="{StaticResource Hub.Muted}" StrokeThickness="1.75"
                    Data="M 9 9 L 13 13 M 6 1 A 5 5 0 1 0 6 11 A 5 5 0 1 0 6 1 Z"/>
              <ScrollViewer x:Name="PART_ContentHost" Margin="26,0,0,0"
                            VerticalAlignment="Center"/>
              <TextBlock x:Name="Placeholder"
                         Text="{TemplateBinding Tag}"
                         Margin="33,0,0,0" VerticalAlignment="Center"
                         Foreground="{StaticResource Hub.Muted}"
                         IsHitTestVisible="False" Visibility="Collapsed"/>
            </Grid>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="Text" Value="">
              <Setter TargetName="Placeholder" Property="Visibility" Value="Visible"/>
            </Trigger>
            <Trigger Property="IsKeyboardFocused" Value="True">
              <Setter TargetName="Bd" Property="BorderBrush" Value="{StaticResource Hub.Accent}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>
```

### 4g. Buttons

Buttons follow the same foreground-inheritance discipline as nav: the `ContentPresenter` inherits `Foreground` via `TextElement.Foreground="{TemplateBinding Foreground}"`, and the hover/disabled triggers flip the button's `Foreground`. Do not hard-code `Foreground` on a child TextBlock inside a button, or the triggers cannot win.

```xml
<!-- ============ BUTTONS ============ -->
<!-- PRIMARY: orange filled, white text, subtle shadow -->
<Style x:Key="Hub.Button.Primary" TargetType="Button">
    <Setter Property="FontFamily"  Value="Segoe UI"/>
    <Setter Property="FontSize"    Value="12"/>
    <Setter Property="FontWeight"  Value="Medium"/>
    <Setter Property="Foreground"  Value="{StaticResource Hub.White}"/>
    <Setter Property="Background"  Value="{StaticResource Hub.Accent}"/>
    <Setter Property="Cursor"      Value="Hand"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Bd" CornerRadius="8" Background="{TemplateBinding Background}"
                  Padding="14,6">
            <Border.Effect>
              <DropShadowEffect Color="#FF000000" BlurRadius="8" ShadowDepth="1"
                                Opacity="0.35" Direction="270"/>
            </Border.Effect>
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              TextElement.Foreground="{TemplateBinding Foreground}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.AccentHover}"/>
            </Trigger>
            <Trigger Property="IsPressed" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.AccentHover}"/>
              <Setter TargetName="Bd" Property="RenderTransform">
                <Setter.Value><ScaleTransform ScaleX="0.99" ScaleY="0.99"/></Setter.Value>
              </Setter>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
              <Setter Property="Cursor"  Value="Arrow"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<!-- SECONDARY: outline -->
<Style x:Key="Hub.Button.Secondary" TargetType="Button">
    <Setter Property="FontFamily"  Value="Segoe UI"/>
    <Setter Property="FontSize"    Value="12"/>
    <Setter Property="FontWeight"  Value="Medium"/>
    <Setter Property="Foreground"  Value="{StaticResource Hub.Muted}"/>
    <Setter Property="Background"  Value="Transparent"/>
    <Setter Property="Cursor"      Value="Hand"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Bd" CornerRadius="8" Background="{TemplateBinding Background}"
                  BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
                  Padding="14,6">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              TextElement.Foreground="{TemplateBinding Foreground}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.Panel2}"/>
              <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
            </Trigger>
            <Trigger Property="IsPressed" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.Panel}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<!-- GHOST: no border -->
<Style x:Key="Hub.Button.Ghost" TargetType="Button">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="FontWeight" Value="Medium"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Muted}"/>
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Cursor"     Value="Hand"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Bd" CornerRadius="8" Background="{TemplateBinding Background}"
                  Padding="14,6">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              TextElement.Foreground="{TemplateBinding Foreground}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.Panel2}"/>
              <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<!-- DANGER -->
<Style x:Key="Hub.Button.Danger" TargetType="Button">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="FontWeight" Value="Medium"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Error}"/>
    <Setter Property="Background" Value="{StaticResource Hub.Error.10}"/>
    <Setter Property="Cursor"     Value="Hand"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Bd" CornerRadius="8" Background="{TemplateBinding Background}"
                  BorderBrush="{StaticResource Hub.Error.30}" BorderThickness="1"
                  Padding="14,6">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              TextElement.Foreground="{TemplateBinding Foreground}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.Error.20}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>
```

### 4h. Status badge + role badge

Badges are best built as a reusable `Border` markup snippet (PowerShell can clone or you can paste per use). The dot is an `Ellipse`; the role badge omits it. Pass already-uppercased badge text.

```xml
<!-- ============ BADGES ============ -->
<!-- SUCCESS status badge (with 6px dot) -->
<Border CornerRadius="4" Padding="8,2"
        Background="{StaticResource Hub.Success.10}"
        BorderBrush="{StaticResource Hub.Success.25}" BorderThickness="1">
  <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
    <Ellipse Width="6" Height="6" Fill="{StaticResource Hub.Success}"
             VerticalAlignment="Center"/>
    <TextBlock Text="ONLINE" Margin="6,0,0,0" FontSize="10" FontWeight="SemiBold"
               Foreground="{StaticResource Hub.Success}" VerticalAlignment="Center"/>
  </StackPanel>
</Border>

<!-- ERROR -->
<Border CornerRadius="4" Padding="8,2"
        Background="{StaticResource Hub.Error.10}"
        BorderBrush="{StaticResource Hub.Error.25}" BorderThickness="1">
  <StackPanel Orientation="Horizontal">
    <Ellipse Width="6" Height="6" Fill="{StaticResource Hub.Error}" VerticalAlignment="Center"/>
    <TextBlock Text="FAILED" Margin="6,0,0,0" FontSize="10" FontWeight="SemiBold"
               Foreground="{StaticResource Hub.Error}" VerticalAlignment="Center"/>
  </StackPanel>
</Border>

<!-- WARNING -->
<Border CornerRadius="4" Padding="8,2"
        Background="{StaticResource Hub.Warning.10}"
        BorderBrush="{StaticResource Hub.Warning.25}" BorderThickness="1">
  <StackPanel Orientation="Horizontal">
    <Ellipse Width="6" Height="6" Fill="{StaticResource Hub.Warning}" VerticalAlignment="Center"/>
    <TextBlock Text="WARNING" Margin="6,0,0,0" FontSize="10" FontWeight="SemiBold"
               Foreground="{StaticResource Hub.Warning}" VerticalAlignment="Center"/>
  </StackPanel>
</Border>

<!-- IDLE (info/blue) -->
<Border CornerRadius="4" Padding="8,2"
        Background="{StaticResource Hub.Info.10}"
        BorderBrush="{StaticResource Hub.Info.25}" BorderThickness="1">
  <StackPanel Orientation="Horizontal">
    <Ellipse Width="6" Height="6" Fill="{StaticResource Hub.Info}" VerticalAlignment="Center"/>
    <TextBlock Text="IDLE" Margin="6,0,0,0" FontSize="10" FontWeight="SemiBold"
               Foreground="{StaticResource Hub.Info}" VerticalAlignment="Center"/>
  </StackPanel>
</Border>

<!-- RUNNING (accent + pulsing dot).
     Animation is on-brand in exactly ONE place: the running/in-progress status dot.
     Nothing else in this system animates by default. -->
<Border CornerRadius="4" Padding="8,2"
        Background="{StaticResource Hub.Accent.10}"
        BorderBrush="{StaticResource Hub.Accent.40}" BorderThickness="1">
  <StackPanel Orientation="Horizontal">
    <Ellipse Width="6" Height="6" Fill="{StaticResource Hub.Accent}" VerticalAlignment="Center">
      <Ellipse.Triggers>
        <EventTrigger RoutedEvent="Loaded">
          <BeginStoryboard>
            <Storyboard RepeatBehavior="Forever" AutoReverse="True">
              <DoubleAnimation Storyboard.TargetProperty="Opacity"
                               From="1" To="0.3" Duration="0:0:0.7"/>
            </Storyboard>
          </BeginStoryboard>
        </EventTrigger>
      </Ellipse.Triggers>
    </Ellipse>
    <TextBlock Text="RUNNING" Margin="6,0,0,0" FontSize="10" FontWeight="SemiBold"
               Foreground="{StaticResource Hub.Accent}" VerticalAlignment="Center"/>
  </StackPanel>
</Border>

<!-- ROLE badge (no dot) -->
<Border CornerRadius="4" Padding="8,2"
        Background="{StaticResource Hub.Panel2}"
        BorderBrush="{StaticResource Hub.Border}" BorderThickness="1">
  <TextBlock Text="ADMIN" FontSize="10" FontWeight="SemiBold"
             Foreground="{StaticResource Hub.Muted}"/>
</Border>
```

### 4i. Admin horizontal sub-tabs

```xml
<!-- ============ SUB-TABS ============ -->
<Style x:Key="Hub.TabControl" TargetType="TabControl">
    <Setter Property="Background"      Value="Transparent"/>
    <Setter Property="BorderThickness" Value="0"/>
    <Setter Property="Padding"         Value="0"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TabControl">
          <DockPanel>
            <!-- Tab strip on a panel bg with bottom divider -->
            <Border DockPanel.Dock="Top"
                    Background="{StaticResource Hub.Panel}"
                    BorderBrush="{StaticResource Hub.Border}" BorderThickness="0,0,0,1">
              <TabPanel IsItemsHost="True" Margin="0" Background="Transparent"/>
            </Border>
            <ContentPresenter ContentSource="SelectedContent"/>
          </DockPanel>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<Style x:Key="Hub.TabItem" TargetType="TabItem">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="FontWeight" Value="Medium"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Muted}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TabItem">
          <Border x:Name="Bd" Background="Transparent"
                  BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
                  CornerRadius="8" Padding="16,12" Margin="0,0,4,0">
            <ContentPresenter x:Name="Hdr" ContentSource="Header"
                              HorizontalAlignment="Center" VerticalAlignment="Center"
                              TextElement.Foreground="{TemplateBinding Foreground}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
            </Trigger>
            <Trigger Property="IsSelected" Value="True">
              <Setter TargetName="Bd" Property="BorderBrush" Value="{StaticResource Hub.Accent}"/>
              <Setter Property="Foreground" Value="{StaticResource Hub.Accent}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>
```

### 4j. DataGrid

Gridlines follow the hub: soft horizontal row dividers only, no vertical lines. Set `GridLinesVisibility="Horizontal"`, `HorizontalGridLinesBrush="{StaticResource Hub.BorderSoft}"`, and `VerticalGridLinesBrush="Transparent"`.

```xml
<!-- ============ DATAGRID ============ -->
<Style x:Key="Hub.DataGrid" TargetType="DataGrid">
    <Setter Property="Background"           Value="{StaticResource Hub.Panel}"/>
    <Setter Property="Foreground"           Value="{StaticResource Hub.Text}"/>
    <Setter Property="BorderBrush"          Value="{StaticResource Hub.Border}"/>
    <Setter Property="BorderThickness"      Value="1"/>
    <Setter Property="RowBackground"        Value="Transparent"/>
    <Setter Property="AlternatingRowBackground" Value="Transparent"/>
    <Setter Property="GridLinesVisibility"  Value="Horizontal"/>
    <Setter Property="HorizontalGridLinesBrush" Value="{StaticResource Hub.BorderSoft}"/>
    <Setter Property="VerticalGridLinesBrush"   Value="Transparent"/>
    <Setter Property="HeadersVisibility"    Value="Column"/>
    <Setter Property="AutoGenerateColumns"  Value="False"/>
    <Setter Property="CanUserAddRows"       Value="False"/>
    <Setter Property="IsReadOnly"           Value="True"/>
    <Setter Property="SelectionMode"        Value="Single"/>
    <Setter Property="RowHeight"            Value="34"/>
    <Setter Property="ColumnHeaderHeight"   Value="32"/>
    <Setter Property="FontFamily"           Value="Segoe UI"/>
    <Setter Property="FontSize"             Value="12"/>
</Style>

<Style x:Key="Hub.DataGridHeader" TargetType="DataGridColumnHeader">
    <Setter Property="Background"      Value="{StaticResource Hub.Panel}"/>
    <Setter Property="Foreground"      Value="{StaticResource Hub.Muted}"/>
    <Setter Property="FontSize"        Value="10"/>
    <Setter Property="FontWeight"      Value="SemiBold"/>
    <Setter Property="Padding"         Value="16,8"/>
    <Setter Property="BorderBrush"     Value="{StaticResource Hub.Border}"/>
    <Setter Property="BorderThickness" Value="0,0,0,1"/>
    <Setter Property="HorizontalContentAlignment" Value="Left"/>
    <!-- Pass already-uppercased header text in the column definition -->
</Style>

<!-- IMPORTANT: every <Setter> must come BEFORE <Style.Triggers>. XamlReader.Load
     (runtime parse, unlike compiled BAML) throws "'Setters' property has already
     been set on 'Style'" if a Setter appears after the Triggers collection. -->
<Style x:Key="Hub.DataGridCell" TargetType="DataGridCell">
    <Setter Property="Background"      Value="Transparent"/>
    <Setter Property="Foreground"      Value="{StaticResource Hub.Text}"/>
    <Setter Property="BorderThickness" Value="0"/>
    <Setter Property="Padding"         Value="16,8"/>
    <Setter Property="FontSize"        Value="12"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="DataGridCell">
          <Border Background="{TemplateBinding Background}" Padding="{TemplateBinding Padding}">
            <ContentPresenter VerticalAlignment="Center"/>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
    <Style.Triggers>
      <Trigger Property="IsSelected" Value="True">
        <Setter Property="Background" Value="{StaticResource Hub.Panel2}"/>
        <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
      </Trigger>
    </Style.Triggers>
</Style>

<Style x:Key="Hub.DataGridRow" TargetType="DataGridRow">
    <Setter Property="Background" Value="Transparent"/>
    <Style.Triggers>
      <Trigger Property="IsMouseOver" Value="True">
        <Setter Property="Background" Value="{StaticResource Hub.Panel2}"/>
      </Trigger>
    </Style.Triggers>
</Style>
```

Wire the sub-styles on the grid:

```xml
<DataGrid Style="{StaticResource Hub.DataGrid}"
          ColumnHeaderStyle="{StaticResource Hub.DataGridHeader}"
          CellStyle="{StaticResource Hub.DataGridCell}"
          RowStyle="{StaticResource Hub.DataGridRow}">
  <DataGrid.Columns>
    <DataGridTextColumn Header="DEVICE" Binding="{Binding Name}" Width="*"/>
    <!-- Mono column for IDs/paths: -->
    <DataGridTextColumn Header="DEVICE ID" Binding="{Binding Id}" Width="180">
      <DataGridTextColumn.ElementStyle>
        <Style TargetType="TextBlock">
          <Setter Property="FontFamily" Value="Consolas"/>
          <Setter Property="Foreground" Value="{StaticResource Hub.Muted}"/>
          <Setter Property="VerticalAlignment" Value="Center"/>
        </Style>
      </DataGridTextColumn.ElementStyle>
    </DataGridTextColumn>
  </DataGrid.Columns>
</DataGrid>
```

### 4k. Detail / master-detail right panel + EmptyState

```xml
<!-- ============ DETAIL PANEL ============ -->
<Style x:Key="Hub.DetailPanel" TargetType="Border">
    <Setter Property="Background"      Value="{StaticResource Hub.Panel}"/>
    <Setter Property="BorderBrush"     Value="{StaticResource Hub.Border}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CornerRadius"    Value="12"/>
    <Setter Property="Padding"         Value="20"/>
</Style>
```

```xml
<!-- EMPTY STATE: centered icon circle + title + description -->
<StackPanel HorizontalAlignment="Center" VerticalAlignment="Center" Margin="0,64">
  <Border Width="44" Height="44" CornerRadius="22"
          Background="{StaticResource Hub.Panel2}"
          BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
          HorizontalAlignment="Center">
    <Path Width="20" Height="20" Stretch="Uniform"
          Stroke="{StaticResource Hub.Muted}" StrokeThickness="1.5"
          HorizontalAlignment="Center" VerticalAlignment="Center"
          Data="M 2 6 L 18 6 M 2 10 L 18 10 M 2 14 L 12 14"/>
  </Border>
  <TextBlock Text="Nothing selected" Margin="0,14,0,0"
             FontSize="14" FontWeight="SemiBold"
             Foreground="{StaticResource Hub.Text}"
             HorizontalAlignment="Center"/>
  <TextBlock Text="Select an item from the list to view its details here."
             Margin="0,4,0,0" MaxWidth="280" TextWrapping="Wrap"
             TextAlignment="Center" FontSize="12"
             Foreground="{StaticResource Hub.Muted}"
             HorizontalAlignment="Center"/>
</StackPanel>
```

### 4l. Custom ScrollBar (~6px)

```xml
<!-- ============ SCROLLBAR ============ -->
<Style x:Key="Hub.ScrollBarThumb" TargetType="Thumb">
    <Setter Property="OverridesDefaultStyle" Value="True"/>
    <Setter Property="IsTabStop" Value="False"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Thumb">
          <Border x:Name="T" CornerRadius="3"
                  Background="{StaticResource Hub.Border}"/>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="T" Property="Background" Value="{StaticResource Hub.Muted}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<Style x:Key="Hub.ScrollBar" TargetType="ScrollBar">
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Width"      Value="6"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ScrollBar">
          <Grid Background="Transparent">
            <Track x:Name="PART_Track" IsDirectionReversed="True">
              <Track.Thumb>
                <Thumb Style="{StaticResource Hub.ScrollBarThumb}"/>
              </Track.Thumb>
              <Track.IncreaseRepeatButton>
                <RepeatButton Command="ScrollBar.PageDownCommand" Opacity="0"
                              Focusable="False" IsTabStop="False"/>
              </Track.IncreaseRepeatButton>
              <Track.DecreaseRepeatButton>
                <RepeatButton Command="ScrollBar.PageUpCommand" Opacity="0"
                              Focusable="False" IsTabStop="False"/>
              </Track.DecreaseRepeatButton>
            </Track>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
    <Style.Triggers>
      <Trigger Property="Orientation" Value="Horizontal">
        <Setter Property="Width"  Value="Auto"/>
        <Setter Property="Height" Value="6"/>
      </Trigger>
    </Style.Triggers>
</Style>
```

You now have a keyed style (`Hub.ScrollBar`) for explicit opt-in. To apply it to every scroll bar in the window, also add this implicit style (no `x:Key`) that derives from it via `BasedOn`. The `BasedOn` form is preferred over `x:Key="{x:Type ScrollBar}"` because it makes the opt-in scope explicit:

```xml
<Style TargetType="ScrollBar" BasedOn="{StaticResource Hub.ScrollBar}"/>
```

### 4m. Dark ComboBox

```xml
<!-- ============ COMBOBOX ============ -->
<!-- Toggle button that forms the closed combobox face -->
<ControlTemplate x:Key="Hub.ComboToggle" TargetType="ToggleButton">
  <Border x:Name="Bd" CornerRadius="8"
          Background="{StaticResource Hub.Code}"
          BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
          Padding="12,6">
    <Grid>
      <ContentPresenter HorizontalAlignment="Left" VerticalAlignment="Center"
                        Margin="0,0,20,0"/>
      <!-- chevron -->
      <Path HorizontalAlignment="Right" VerticalAlignment="Center"
            Width="9" Height="6" Stretch="Uniform"
            Fill="{StaticResource Hub.Muted}"
            Data="M 0 0 L 9 0 L 4.5 6 Z"/>
    </Grid>
  </Border>
  <ControlTemplate.Triggers>
    <Trigger Property="IsMouseOver" Value="True">
      <Setter TargetName="Bd" Property="BorderBrush" Value="{StaticResource Hub.Muted}"/>
    </Trigger>
    <Trigger Property="IsChecked" Value="True">
      <Setter TargetName="Bd" Property="BorderBrush" Value="{StaticResource Hub.Accent}"/>
    </Trigger>
  </ControlTemplate.Triggers>
</ControlTemplate>

<Style x:Key="Hub.ComboBoxItem" TargetType="ComboBoxItem">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
    <Setter Property="Padding"    Value="12,7"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBoxItem">
          <Border x:Name="Bd" Background="Transparent" Padding="{TemplateBinding Padding}">
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsHighlighted" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.Panel2}"/>
            </Trigger>
            <Trigger Property="IsSelected" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="{StaticResource Hub.Panel2}"/>
              <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>

<Style x:Key="Hub.ComboBox" TargetType="ComboBox">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
    <Setter Property="ItemContainerStyle" Value="{StaticResource Hub.ComboBoxItem}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBox">
          <Grid>
            <ToggleButton x:Name="PART_ToggleButton"
                          Focusable="False"
                          Template="{StaticResource Hub.ComboToggle}"
                          IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
              <ContentPresenter
                  Content="{TemplateBinding SelectionBoxItem}"
                  ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
            </ToggleButton>
            <Popup x:Name="PART_Popup" AllowsTransparency="True"
                   Placement="Bottom" IsOpen="{TemplateBinding IsDropDownOpen}"
                   PopupAnimation="Fade" Focusable="False">
              <Border CornerRadius="8" Margin="0,4,0,0"
                      Background="{StaticResource Hub.Panel}"
                      BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
                      MinWidth="{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}">
                <ScrollViewer MaxHeight="240">
                  <ItemsPresenter/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>
```

### 4n. Bonus controls every real tool needs

**Inline alert (banner):**

```xml
<!-- Inline alert: swap the .10/.25 + text brushes per severity -->
<Border CornerRadius="8" Padding="12,10"
        Background="{StaticResource Hub.Warning.10}"
        BorderBrush="{StaticResource Hub.Warning.25}" BorderThickness="1">
  <StackPanel Orientation="Horizontal">
    <Ellipse Width="8" Height="8" Fill="{StaticResource Hub.Warning}"
             VerticalAlignment="Center"/>
    <TextBlock Margin="10,0,0,0" VerticalAlignment="Center"
               Foreground="{StaticResource Hub.Text}" FontSize="12"
               Text="Configuration drift detected on 3 endpoints."/>
  </StackPanel>
</Border>
```

**Toast (subtle shadow allowed):**

```xml
<Border CornerRadius="8" Padding="14,10"
        Background="{StaticResource Hub.Panel2}"
        BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
        HorizontalAlignment="Right" VerticalAlignment="Bottom" Margin="24">
  <Border.Effect>
    <DropShadowEffect Color="#FF000000" BlurRadius="16" ShadowDepth="2" Opacity="0.45"/>
  </Border.Effect>
  <StackPanel Orientation="Horizontal">
    <Ellipse Width="8" Height="8" Fill="{StaticResource Hub.Success}" VerticalAlignment="Center"/>
    <TextBlock Margin="10,0,0,0" Foreground="{StaticResource Hub.Text}" FontSize="12"
               Text="Deployment queued."/>
  </StackPanel>
</Border>
```

**Loading spinner (indeterminate ring via RotateTransform):**

```xml
<Canvas Width="20" Height="20" RenderTransformOrigin="0.5,0.5">
  <Ellipse Width="20" Height="20"
           Stroke="{StaticResource Hub.Border}" StrokeThickness="2"/>
  <Path Stroke="{StaticResource Hub.Accent}" StrokeThickness="2" StrokeStartLineCap="Round"
        Data="M 10 0 A 10 10 0 0 1 20 10"/>
  <Canvas.RenderTransform>
    <RotateTransform x:Name="SpinRot" Angle="0" CenterX="10" CenterY="10"/>
  </Canvas.RenderTransform>
  <Canvas.Triggers>
    <EventTrigger RoutedEvent="Loaded">
      <BeginStoryboard>
        <Storyboard RepeatBehavior="Forever">
          <DoubleAnimation Storyboard.TargetName="SpinRot"
                           Storyboard.TargetProperty="Angle"
                           From="0" To="360" Duration="0:0:0.9"/>
        </Storyboard>
      </BeginStoryboard>
    </EventTrigger>
  </Canvas.Triggers>
</Canvas>
```

**Indeterminate ProgressBar:**

```xml
<Style x:Key="Hub.ProgressBar" TargetType="ProgressBar">
    <Setter Property="Height"      Value="4"/>
    <Setter Property="Background"  Value="{StaticResource Hub.Panel2}"/>
    <Setter Property="Foreground"  Value="{StaticResource Hub.Accent}"/>
    <Setter Property="BorderThickness" Value="0"/>
</Style>
```

**CheckBox (dark, accent check):**

```xml
<Style x:Key="Hub.CheckBox" TargetType="CheckBox">
    <Setter Property="FontFamily" Value="Segoe UI"/>
    <Setter Property="FontSize"   Value="12"/>
    <Setter Property="Foreground" Value="{StaticResource Hub.Text}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="CheckBox">
          <StackPanel Orientation="Horizontal">
            <Border x:Name="Box" Width="16" Height="16" CornerRadius="4"
                    Background="{StaticResource Hub.Code}"
                    BorderBrush="{StaticResource Hub.Border}" BorderThickness="1"
                    VerticalAlignment="Center">
              <Path x:Name="Check" Width="9" Height="9" Stretch="Uniform"
                    Stroke="{StaticResource Hub.White}" StrokeThickness="2"
                    Data="M 0 5 L 4 9 L 10 0" Visibility="Collapsed"/>
            </Border>
            <ContentPresenter Margin="8,0,0,0" VerticalAlignment="Center"/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="Box"   Property="Background" Value="{StaticResource Hub.Accent}"/>
              <Setter TargetName="Box"   Property="BorderBrush" Value="{StaticResource Hub.Accent}"/>
              <Setter TargetName="Check" Property="Visibility" Value="Visible"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
</Style>
```

**Code / log surface:**

```xml
<Border CornerRadius="8" Padding="12"
        Background="{StaticResource Hub.Code}"
        BorderBrush="{StaticResource Hub.Border}" BorderThickness="1">
  <TextBox IsReadOnly="True" Background="Transparent" BorderThickness="0"
           Foreground="{StaticResource Hub.Text}"
           FontFamily="Consolas" FontSize="12"
           VerticalScrollBarVisibility="Auto"
           TextWrapping="NoWrap"
           Text="C:\Tools\deploy.ps1 -Ring 1&#x0a;[2026-06-16 09:12:04] INFO  Started&#x0a;[2026-06-16 09:12:07] OK    3 devices"/>
</Border>
```

(`&#x0a;` is the ASCII newline entity - safe in XAML, no literal non-ASCII bytes. Always use it for multi-line literal text in attributes.)

---

## 5. Spacing System

Base unit = 4. Use these steps; do not invent in-between values.

| Step | px | Where |
|---|---|---|
| 0.5 | 2 | nav item vertical gap (Margin 0,1 -> ~2 between), hairline offsets |
| 1 | 4 | badge vertical padding, title-to-meta gap |
| 1.5 | 6 | input vertical padding, dot-to-text gap, scrollbar width |
| 2 | 8 | nav horizontal padding, badge horizontal padding, button/input radius, small gaps |
| 2.5 | 10 | brand logo-to-text gap, footer chip-to-text gap |
| 3 | 12 | nav item horizontal padding, card radius, nav-icon-to-label gap, input horizontal padding |
| 3.5 | 14 | button horizontal padding, card title top margin |
| 4 | 16 | card grid gap, table cell horizontal padding, brand padding |
| 5 | 20 | card padding |
| 6 | 24 | **page content padding** |
| 14 | 56 | brand header height |
| 16 | 64 | empty-state vertical padding |

Component fixed dimensions: sidebar width 210 (the active nav item is a raised selected surface, never a bar), logo square 32, icon container 40, avatar 30, status dot 6, category dot 8, nav icon 15.

---

## 6. Hard Rules Recap

1. **ASCII only.** No byte > 127 anywhere in any `.ps1` or `.xaml`. Use `-` for all dashes, straight `'`/`"`, and `&amp;`/`&lt;`/`&gt;`/`&#x0a;` entities in XAML. Non-ASCII silently breaks parsing under `-WindowStyle Hidden`.
2. **Fonts: Segoe UI for all UI text, Consolas for monospace** (versions, logs, paths, IDs, timestamps). IBM Plex Sans/Mono are never referenced.
3. **Borders, not shadows.** Cards/panels use a 1px `Hub.Border` and no effect. Only the primary button and toasts carry a subtle `DropShadowEffect`.
4. **One accent, used sparingly.** Orange (#E06420) appears on: primary button, focus border, running badge, occasional category dot. Tints are explicit `#AARRGGBB` (faint tint = `Hub.Accent.08`, hover-card border / focus ring = `Hub.Accent.40`, semantic badges = `.10` bg + `.25` border). The 0.30 alpha byte is pinned to `0x4D` everywhere.
5. **Uppercase tracked micro-labels** (10px SemiBold muted, `Hub.MicroLabel`) on nav-adjacent labels, table headers, badges, section labels. Pre-uppercase the text in PowerShell; use the per-character `Run` technique (`Set-TrackedLabel`) only where exact tracking is required.
6. **No edge-bar indicators, on any side:** the selected nav item (and any selected row or item) is a raised neutral surface: `Hub.Panel2` background, a 1px `Hub.Border` hairline all the way round, `Hub.Text` SemiBold. Never a left, right, top or bottom accent bar or stripe; colour comes from tinted fills, tinted hairlines, icon tiles and dots.
7. **Focus = accent border.** Inputs, combobox, and focusable surfaces switch `BorderBrush` to `Hub.Accent` on keyboard focus / open.
8. **Geometry:** card 12, button/input/combobox/nav 8, badge 4, avatar/dot circle. Page padding 24, card padding 20.
9. **Disabled = Opacity 0.4** on every interactive control.
10. **Foreground inheritance.** Do NOT set `Foreground` on inner `TextBlock`/content of nav items and buttons; let the `ListBoxItem`/`Button` `IsSelected`/`IsMouseOver` triggers drive foreground via `TextElement.Foreground="{TemplateBinding Foreground}"` on the `ContentPresenter`. A local value on a child silently beats the trigger.
11. **Robust over clever - keep every required template PART.** When you retemplate a control, retain the parts WPF wires by name, or the control breaks under `XamlReader.Load`: `PART_ContentHost` (TextBox), `PART_Track` (ScrollBar), `PART_ToggleButton` + `PART_Popup` (ComboBox), `ItemsPresenter` (items popups). ScrollBar page buttons stay present at `Opacity="0"`, `Focusable="False"`.
12. **All `<Setter>` before `<Style.Triggers>`.** In a `Style`, every `Setter` must appear ahead of the `Style.Triggers` (and any other `Style.*` property element). Compiled BAML tolerates interleaving, but `XamlReader.Load` throws `'Setters' property has already been set on 'Style'` if a `Setter` follows a property element. This applies to a `Setter Property="Template"` too - put it with the other setters, above the triggers. Verify before shipping with a checker that walks each `Style`'s child order, not just an XML well-formedness check (well-formed XML does not catch this).

Self-check performed: (a) every character scanned for bytes > 127 - none present (all dashes are `-`, all quotes straight, all special chars are entities including `&#x0a;`); (b) only `Segoe UI` and `Consolas` are referenced as fonts (IBM Plex appears solely as a prohibition); (c) every XAML block is `XamlReader.Load`-compatible (no `x:Class`, no code-behind, no `{x:Static}` against own assembly, no `d:` design attributes, all required template PARTs retained); (d) all `x:Key` names are unique with no duplicates or conflicts. The document is clean.
