---
name: Code-map viewer
description: A codebase read like a building-instructions booklet, a factory assembled step by step.
colors:
  page: "#e3ecf3"
  page-deep: "#d3dfe9"
  ink: "#1b1d21"
  paper: "#ffffff"
  shade: "#c4d1dc"
  rule: "#b8c6d2"
  brick-red: "#d01012"
  brick-yellow: "#f5cd2f"
  brick-blue: "#0055bf"
  brick-green: "#237841"
  slate: "#5c6b78"
  slate-text: "#4f5d69"
  steel: "#c9d8e6"
  shelf: "#f2f5f8"
  amber: "#7a5c00"
  picked: "#0055bf"
  picked-wash: "#d4e3f7"
typography:
  display:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "92px"
    fontWeight: 800
    lineHeight: 0.9
    fontVariation: "'wdth' 62"
    fontFeature: "'tnum' 1"
  headline:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 70"
  title:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.15
    fontVariation: "'wdth' 85"
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "'tnum' 1"
  label:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "10px"
    fontWeight: 700
    letterSpacing: "0.08em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12px"
  world-name:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: "20px"
  world-name-small:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: "18px"
  world-subline:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 500
  world-code:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 700
  world-plate:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "10.5px"
    fontWeight: 700
  world-bus:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 700
rounded:
  none: "0px"
spacing:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "12px"
  xxl: "14px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "8px"
  button-primary-hover:
    backgroundColor: "{colors.brick-blue}"
    textColor: "{colors.paper}"
  button-primary-disabled:
    backgroundColor: "{colors.shade}"
    textColor: "{colors.slate-text}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "5px 12px"
  button-secondary-hover:
    backgroundColor: "{colors.brick-yellow}"
  section-tab:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    padding: "1px 6px"
  code-chip:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    padding: "1px 5px"
  floor-current:
    backgroundColor: "{colors.brick-yellow}"
    textColor: "{colors.ink}"
    padding: "4px 6px"
  input-search:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "6px 8px"
  step-numeral:
    backgroundColor: "{colors.brick-yellow}"
    textColor: "{colors.ink}"
    typography: "{typography.display}"
    padding: "10px 16px 6px"
  world-code-tab:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.world-code}"
    height: "19px"
  world-plate-box:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.world-plate}"
    height: "17px"
  world-bus-label:
    backgroundColor: "{colors.steel}"
    textColor: "{colors.ink}"
    typography: "{typography.world-bus}"
    height: "17px"
---

# Design System: Code-map viewer

## Overview

**Creative North Star: "The Instruction Booklet"**

The codebase is read like a toy-brick building-instructions booklet: a factory assembled step by step on a pale blue-grey page. Every module is a flat-shaded white block with a hairline black keyline and a short code (S2, P3, X1) on a black tab. Brick colours appear only where they have a job, and no kind is ever carried by colour alone: every line kind also has its own stroke form, every machine kind its own icon and silhouette.

The surface is dense and operational, a desktop tool for a developer reviewing code an agent wrote. Chrome (left rail, collapsible inspector, trace pane) speaks the same material as the floor: square corners, 1px ink keylines, black section tabs, the same flat shade plate. One blue marks what is picked, the same in both panes: the floor's selection ring, the trace pane's focus row (a pale blue wash under a blue keyline), the row whose detail is open, and the Trace buttons. The floor wears one blue ring at a time. The thesis refuses the category default of a dark canvas of rounded node cards and bezier edges.

**Key Characteristics:**
- Pale booklet page, white keylined modules, a flat 6px shade plate for every raised thing.
- Brick colours with jobs: red writes and alerts, yellow the outside world, blue streams, green events, slate reads, amber batch.
- Archivo everywhere, variable width from 62% to 125%, tabular figures on.
- Orthogonal lines; each interaction kind has its own stroke form.
- Guesses look like guesses: an inferred line wears a dashed paper ring on each tile.

## Colors

A cool, paper-pale field with black keylines, where saturated brick colours appear only to carry a meaning.

### Primary
- **Keyline Ink** (#1b1d21): every keyline, code tab, section tab, primary button, rail header, and all world text. The voice of the booklet.

### Secondary
- **Brick Yellow** (#f5cd2f): the outside world (external systems), the current floor in the switcher, the step numeral plate, payload tags and moving parts, saved notes. Yellow never marks what is picked: among marks it means the outside world only; hover fills on secondary buttons and the current floor's plate keep it. Text on yellow is always ink: slate on yellow is 3.6:1 and fails.
- **Brick Blue** (#0055bf): streams (pipe core), the picked mark (`--picked`: the floor's selection ring, the trace pane's focus and pointed rows, the Trace buttons' hover), the OPEN tab, focus outline, links, primary-button hover.

### Tertiary
- **Brick Red** (#d01012): DB writes and alerts; error borders.
- **Brick Green** (#237841): events (drone dots and drones).
- **Batch Amber** (#7a5c00): batch jobs (train track with sleepers, wagons).

### Neutral
- **Booklet Page** (#e3ecf3): app and floor background; the light core of a belt.
- **Page Deep** (#d3dfe9): left rail and collapsed inspector.
- **Paper** (#ffffff): machine faces, inspector, cards, inputs, flight plates.
- **Shade Plate** (#c4d1dc): the flat-shaded side of every module and raised panel; disabled button fill.
- **Hairline Rule** (#b8c6d2): dividers between rail and inspector sections.
- **Steel** (#c9d8e6): the DB lanes (a steel road with a dashed centre line) and their labels; warehouses.
- **Shelf** (#f2f5f8): library shelves and stacked group plates.
- **Read Slate** (#5c6b78): DB-read lines and machine sublines on the canvas (4.6:1 on page).
- **Slate Text** (#4f5d69): secondary text in chrome (the stylesheet's `--slate`), darker than the canvas slate so it clears 5:1 on page-deep.
- **Picked Wash** (#d4e3f7): the trace pane's focus row under its 2px blue keyline (12.9:1 with ink); text selection.

### Named Rules
**The Colour Has a Job Rule.** A brick colour is never decoration. If a hue does not map to a kind (write, outside world, stream, event, read, batch) or to selection/focus, it does not appear.

**The Blue Means Picked Rule.** What is picked — the floor's selected box, the trace's focus, the row whose detail is open — wears the same blue in both panes. One ring on the floor at a time: the row whose detail is open, else the trace's focus. Yellow never marks a pick.

**The Never Alone Rule.** No kind is carried by colour alone: each line kind has its own stroke form and each machine kind its own icon and silhouette.

**The Ink on Yellow Rule.** Anything on yellow is set in ink. An external's endpoint lives in its subline in ink, never slate.

## Typography

**Display Font:** Archivo (bundled variable font, weight 100 to 900, width 62% to 125%; system-ui fallback)
**Body Font:** Archivo
**Label/Mono Font:** ui-monospace (SFMono-Regular, Menlo) for code and commit hashes only

**Character:** One grotesque doing every job, with condensed widths for numerals and titles and tabular figures so counts and codes align like a parts list.

### Hierarchy
- **Display** (800, 92px, 0.9, width 62%): unused since the trace pane replaced the step player.
- **Headline** (800, 22px, 1.1, width 70%): the repository name in the rail header. The empty-state title is the same voice at 34px, width 75%.
- **Title** (700, 18px, 1.15, width 85%): the inspector's selected-item name; the trace pane's heading at 15px.
- **Body** (400, 13px, 1.45, tabular figures): all chrome text; help copy capped at 60ch.
- **Label** (700, 10px, 0.08em, uppercase): section tabs and code chips. Floor numerals in the switcher use 800, 15px, width 70%.

### World type (on the PixiJS floor)
Sizes are chosen to stay legible when floor 0 is fitted to the window.
- **Machine name** (600, 17px, line 20px); methods and externals 15px.
- **Subline** (500, 15.5px): kind and counts in slate; an external's endpoint in ink.
- **Code tab** (700, 14.5px on a 19px ink tab).
- **Flight plate** (700, 10.5px on a 17px paper box edged in the flight's colour); a consumer's tag is paper on ink.
- **Lane label** (700, 12px on a 17px steel plate).
- **Roof utility tab** (700, 11px on a 16px keylined paper tab); door name 600, 12.5px.

### Named Rules
**The Whole Word Rule.** Names are never cut mid-word. They drop the prefix every item on the floor shares and wrap after `-`, `.`, `_`, `/` or a space, before `(` or at a camelCase capital. A name takes the largest size at which it wraps whole; if that wrap breaks inside a word, it takes the next size down when that breaks between words (never more than one size down). When even the smallest size does not fit, the front is kept and the last line ends in an ellipsis: a name is never cut from the front.

## Layout

Desktop only, 1024px minimum width; there is no phone or narrow layout. A three-column shell fills the viewport: left rail (232px), the floor canvas (fluid, ink-keylined left and right), and the inspector (312px, collapsible to a 36px vertical tab, open by default). The floor switcher F0 to Fn lives at the top of the left rail, newest floor on top, followed by Find, the floor's item list (On this floor) and the pinned traces, each section folding to its heading and count, with "Save for the agent (N)" (comments plus pin changes), problems and still-motion pinned at the rail foot. The legend sits top-left over the canvas; Fit sits bottom-right. A trace opens a pane under the floor and inspector, split from them by an 8px divider (drag it, or focus it and press ↑/↓ for 5% steps; 20 to 80% of the window, 45% to start, remembered in browser storage); Maximize fills the whole window and Restore returns it. The floor keeps its zoom above the pane.

Spacing runs on a tight 4/6/8/10/12/14px rhythm: section padding 10px 12px in the rail and 10px 14px in the inspector, overlays inset 12px from the canvas edge. On the floor, positions come from the map's layout; the camera fits floor 0 at 94% of the visible area.

## Elevation & Depth

Depth is flat. There are no blurred shadows anywhere. Every raised thing, on the floor or in the chrome, sits on a solid shade plate offset 6px right and 6px down, and that plate is keylined on the floor. Tonal layering does the rest: page, page-deep rail, paper panels.

### Shadow Vocabulary
- **Shade plate** (`box-shadow: 6px 6px 0 #c4d1dc`): trace pane boxes and any raised chrome panel; on the floor, a keylined #c4d1dc rect offset (6, 6) behind each module.
- **Group stack**: groups draw two extra shelf plates offset (5, -5) and (10, -10) behind the face.

### Named Rules
**The Flat Plate Rule.** Depth is the 6px shade plate, everywhere. No blur, no spread, no second shadow size.

## Shapes

Square corners throughout (0px radius). Borders are 1px ink keylines (device-pixel on the canvas); selection is a 3px blue ring set 5px out; a trace pane row under the pointer rings its box in a thin ink line (1.5px) set 9px out, just outside the blue ring, so a hover never reads as a pick. Services carry a 6px ink roofline. Method machines have small ink ports on both sides. Lines route orthogonally.

**The Hatched Means Inferred Rule.** A guess looks like a guess: an inferred line's tiles wear a dashed paper ring (4 on, 3 off, inset 2px); inferred rows in the inspector are hatched at 135 degrees. A solid surface is never hatched for texture; a DB lane is solid steel.

## Components

### Buttons
- **Shape:** square (0px), 1px ink keyline or none.
- **Primary:** ink fill, paper text, 700 weight, 8px padding (6px 12px inline); hover turns brick blue; disabled is shade fill with slate text.
- **Secondary:** paper fill, 1px ink keyline, 5px 12px, 600 weight; hover fills yellow.
- **Focus:** 2px blue outline, 2px offset, on every focusable element.

### Section tabs and code chips
- **Section tab:** ink block with paper text, 10px uppercase 700, 0.08em tracking, 1px 6px; heads every rail and inspector module ("Floors", "Find", "On this floor (12)", "Pinned traces (6)", "Export comments"). In the rail the tab is a button that folds its section (a chevron before the name), remembered per browser; under the pointer it turns ink on paper (never blue: blue means picked). In the inspector header it names the selected item's kind.
- **Code chip:** the same ink block carrying a short code (S2, P3, X1) beside a name.
- **Kind chip:** 10px 700 with an ink keyline, filled with the kind's brick colour (write red, stream blue, event green, external yellow).

### Inputs / Fields
- **Style:** paper fill, 1px ink keyline, 0px radius, 6px 8px; placeholder in slate.
- **Focus:** the global 2px blue outline.

### Navigation
- **Floor switcher (left rail):** a list from F0 up; each row a condensed 800 floor numeral plus name. Current floor is yellow with an ink keyline and 700 weight; the floor you can go down to is a dashed ink keyline in blue text; hover adds an ink keyline.
- **Rail lists:** rows highlight to paper on hover; selected rows are paper with a 1px inset ink outline and 700 weight.
- **Inspector:** collapsible right panel, open by default; collapsed it becomes a 36px page-deep strip with a vertical ink tab. Showing or hiding it keeps the floor's zoom and the point at its centre.

### Machines (floor)
White face (yellow for externals, shelf for libraries) with a 1px ink keyline, the ink code tab top-left, the name and subline inside. Utility hubs a machine uses show as small keylined paper code tabs on its roof. A selected machine with a floor inside shows a blue OPEN tab below.

### Lines (floor)
- **Belt (request):** 5px ink band with a 1.4px page core.
- **Drone path (event):** green round dots, 2 on 6 off, 3px.
- **Pipe (stream):** 9px ink casing with a 4.5px blue core.
- **Train (batch):** 2.5px amber track with sleepers.
- **Tap (DB):** 3px red for writes, 3px slate for reads.
- **Code dependency:** 1.6px ink hairline.

### Layers (floor)
A heavily used item (`hubs`, fan-in 8 or more) gets an extra layer holding every line into and out of it; batch rails stay in the base. The layers button (stacked icon, count badge) shows only on a floor with one; its label is the shown layer's map code (`S7·P1·F1`) or "Base", and the list reads `Base`, then `S7·P1·F1 · 10`, the full name on hover. While a layer shows, its lines are on top at full strength, the base fades to 12% and buildings stay put; Esc or a click on empty floor returns to the base. The item wears a `used by N` paper-on-ink badge beside its machine, clear of every line and as large as its room allows at Fit; a tap opens its layer. Code links (F0) is a separate toggle, not a layer.

### Trace pane
A paper panel under the floor with an ink top keyline. Its head carries a "Trace" section tab, the focus (code chip and name, 15px, a line has no chip; for a container or a line its kind and seed count in slate ("feature-store · service · 2 entry points", a `show all N` chip above five)), the method and box counts, a Upstream/Both/Downstream switch, and the zoom (100%) and Fit trace, Pin/Unpin, Maximize/Restore and Close. Boxes, one per service or library (a table, topic, external or datastore gets its own), are paper with an ink keyline and the 6px shade plate; a library is on the shelf tint and an external on yellow. A box head holds the code chip, name and kind; rows below hold a method name over a slate data line. Inside a box calls are an indented call tree, 14px per level up to 4 levels, one elbow arrow per call. Arrows between boxes are orthogonal and run below the boxes they skip: solid for confirmed, dashed for inferred, dotted for implemented-by, with the floor's kind colours (event green, stream blue, batch amber, write red, read slate). The focus row (each seed row, for a container or a line) is on the pale blue wash with a 2px blue keyline; while another row's detail is open that row takes the keyline and the focus keeps its wash; a loop is marked ↺; a hop known only to a service, library or class is an italic row "entry method not known"; a side above 5 neighbours shows its total, then "show all N"; a `+N` chip adds one hop; calls into another library fold into one box ("common · N calls") with an Open chip. Drag the background (never a row or an arrow) to pan; the wheel scrolls; Ctrl+wheel or a pinch zooms 50–200 %; Fit trace shows the whole trace; the arrow keys, + − and 0 do the same from the keyboard. The floor and the pane show one subject: starting a trace clears the selection, and exactly one box wears the selection ring — the row whose detail is open, else the trace's focus (lit, without the ring, while a row is pointed). The inspector shows that item (a row whose item has no ring on this floor still: its detail is open; a line's trace, the line while the shown floor has it), without selecting it, so its comments attach there; a Trace button for the trace's own focus is disabled ("Already traced"); when the pane closes it returns to the floor. Any box clicked on the floor re-targets the trace in the same direction: a method, table, topic or external from itself, a datastore from its tables, a service, library, package, file, class or group from the entry points inside it, else its boundary methods (those a traced line crosses its edge at), else itself; a line from both ends of what it carries (no Pin: pins start from map nodes; nor can a floor group be pinned); the box the focus is drawn as on the shown floor keeps the trace as it is. A node picked by name (Find, a rail list, a link) re-targets the trace unless it is the focus itself. The head names a class or container by its item name ("BillingService.Live"); a new pin offers a container's qualified name ("notifier / app / main.py"), with no direction in any default title: the rail shows that. A clicked row is ringed on the floor; when its item is on another floor the detail panel names that floor ("on floor F2 · billing") beside Show on floor, which travels one floor at a time, and the door of the shown floor that leads toward it wears the ring ("it's that way"). A newly ringed box out of view brings the camera to it at the same zoom (a pan, never a zoom; one already in view leaves the camera still), and when the pane opens or its divider rises over the focus or the selection, the floor centres it again; Restore centres it whenever it is not wholly in view. The detail panel sits on the pane's right (320px) and stays visible when the pane is maximized: it names the row or arrow, then shows the entry point's or the data types' examples under "example values, not computed", else the type's fields, else the signature. Esc closes one thing per press: a layer, then the pin form, then the detail panel, then the pane, then the selection.

## Do's and Don'ts

### Do:
- **Do** give every raised thing the 6px flat shade plate (#c4d1dc), on the floor and in the chrome.
- **Do** set anything on yellow in ink (#1b1d21), including an external's endpoint subline.
- **Do** keep world type at its fit-legible sizes: names 17px, methods and externals 15px, sublines 15.5px, code tabs 14.5px on 19px tabs, flight plates 10.5px on 17px boxes, lane label 12px.
- **Do** wrap names at `.`, `_`, `/`, a space, or before `(`, drop the shared floor prefix, and let a name shrink at most one size to get a clean break between words.
- **Do** place plates and tags beside what they name, and draw moving parts above tags.
- **Do** pair every kind colour with a distinct stroke form or icon.

### Don't:
- **Don't** use blurred or soft shadows, or any shade offset other than 6px.
- **Don't** round corners.
- **Don't** dash or hatch a surface that is confirmed; dashing and hatching mean inferred.
- **Don't** cut a name mid-word or from the front, or shrink it more than one size to avoid a bad break.
- **Don't** set slate text on yellow (3.6:1).
- **Don't** design a phone or narrow layout; the viewer is desktop-only from 1024px.
