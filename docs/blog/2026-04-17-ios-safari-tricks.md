---
layout: post
title: "iOS Safari Performance Tricks I Wish I Knew Earlier"
date: 2026-04-17 22:15:00 -0400
tags: [ios, safari, mobile, css, web]
---

I spent an afternoon making a web app feel right on iOS Safari. Most of what I needed turned out to be five CSS rules and three meta tags. Writing this down so other people don't lose the same afternoon.

Target: [Virtual Brainstem on iPhone](https://kody-w.github.io/rappterbook/virtual-brainstem.html). Before: layout broken by the browser chrome, inputs auto-zoomed, notch ate content. After: clean, usable, almost-native.

## 1. Use `100dvh`, not `100vh`

Classic bug. `100vh` on iOS Safari doesn't mean "the visible height of the viewport." It means "the viewport height when the address bar is hidden." When the address bar is visible — which is most of the time — `100vh` is *larger than the actual viewport*, and content at the bottom of your page gets clipped.

Fix: the `dvh` unit. Dynamic viewport height. Updates when the address bar moves.

```css
html, body {
  height: 100%;       /* fallback for older browsers */
  height: 100dvh;     /* iOS: actual visible height */
}
```

Supported in Safari 15.4+ (mid-2022). Older iOS will fall back to `100%` which is usually close enough.

## 2. 16px inputs, always

If *any* `<input>`, `<textarea>`, or `<select>` has a computed `font-size` less than 16px, iOS Safari zooms in when the element gets focus. Every time. No way to disable. The zoom is "accessibility."

Result: user taps an input, viewport jumps, layout breaks, user's thumb lands on the wrong thing.

Fix: 16px minimum for every focusable input:

```css
input, textarea, select {
  font-size: 16px;
}
```

Not 0.95rem. Not 15px. **16px.** This is the only number that makes iOS leave the viewport alone.

If you want small inputs for aesthetic reasons on desktop, use a media query:

```css
input { font-size: 16px; }
@media (min-width: 900px) {
  input { font-size: 14px; }  /* desktop can be smaller */
}
```

## 3. Safe-area insets for the notch + home indicator

The iPhone X and later have a notch at the top and a home-indicator area at the bottom. If your page extends edge-to-edge with `viewport-fit=cover`, content under those zones is physically occluded.

Fix: `env(safe-area-inset-*)`. Four variables (top, right, bottom, left) that tell you how much to reserve.

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```

```css
body {
  padding: env(safe-area-inset-top)
           env(safe-area-inset-right)
           env(safe-area-inset-bottom)
           env(safe-area-inset-left);
}
```

In landscape on an iPhone the left inset is non-zero too. Applying to all four sides prevents the notch from overlapping your header in any rotation.

## 4. Disable overscroll bouncing

By default iOS Safari bounces your whole page when you scroll past the top or bottom of the document. For an app-like UI (chat pane, fixed header) this feels wrong — the whole page moves around the stationary header.

Fix:

```css
html, body {
  overscroll-behavior: none;
}
```

Scoped to inner scrollable regions if you still want bounce for the main document:

```css
#chat-messages {
  overscroll-behavior: contain;
}
```

## 5. Momentum scrolling for overflow regions

If you have a `overflow-y: auto` div that's not the document itself (like a chat pane), older iOS versions don't give it momentum scrolling by default. Fix:

```css
#chat-messages {
  -webkit-overflow-scrolling: touch;
}
```

Modern iOS handles this automatically, but the rule doesn't hurt. Cheap insurance.

## 6. No tap highlight

Safari draws a gray rectangle over any element you tap. It's meant as feedback but looks amateurish in a polished UI.

```css
body { -webkit-tap-highlight-color: transparent; }
```

If you want deliberate feedback on buttons, add your own `:active` state.

## 7. Big tap targets

Apple's HIG says 44×44 points is the minimum tap target. Web practice is looser but anything under ~36px causes misfires. Bump buttons and checkboxes:

```css
button {
  min-height: 38px;
  min-width: 38px;
  padding: 0.5rem 0.9rem;
}
input[type="checkbox"] {
  width: 20px;
  height: 20px;  /* default is ~13px — too small */
}
```

## 8. Add-to-Home-Screen meta tags

If you want your web app to feel native when the user adds it to their home screen (share icon → Add to Home Screen), add these:

```html
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="MyApp">
<meta name="theme-color" content="#0d1117">
<meta name="color-scheme" content="dark">
```

Result: tap the home-screen icon → app launches full-screen with your theme color behind the status bar. No browser chrome. Looks like a real app.

The `apple-mobile-web-app-title` sets the name shown under the icon. Short names read better on a 4-column home screen grid.

## 9. Sidebar as slide-over drawer on mobile

If you have a sidebar layout on desktop, don't try to cram it next to your main content on mobile. It won't fit. Instead, make the sidebar slide over the main content from the right.

```css
@media (max-width: 800px) {
  aside {
    position: absolute;
    inset: 0 0 0 auto;
    width: min(92vw, 380px);
    transform: translateX(100%);
    transition: transform 0.22s ease-out;
    z-index: 50;
  }
  aside.open { transform: translateX(0); }
  .drawer-backdrop {
    position: absolute; inset: 0; z-index: 40;
    background: rgba(0,0,0,0.45);
    opacity: 0; pointer-events: none;
    transition: opacity 0.22s ease-out;
  }
  aside.open ~ .drawer-backdrop { opacity: 1; pointer-events: auto; }
}
```

The backdrop div dims the main area and is tappable to dismiss. Total: ~20 lines of CSS for a UX pattern users expect on mobile.

## 10. Prevent auto-text-size-adjust on rotate

When you rotate the device, iOS sometimes decides your text is too small for the new orientation and scales it up, breaking your layout.

```css
html { -webkit-text-size-adjust: 100%; }
```

Locks text size to what you specified. Never "helpfully" adjusted.

## The checklist

Things that were bugs before and aren't anymore:

- [ ] Viewport meta has `viewport-fit=cover`
- [ ] `100dvh` somewhere in the layout
- [ ] All `<input>` and `<textarea>` have `font-size: 16px`
- [ ] `env(safe-area-inset-*)` padding on the outermost container
- [ ] `overscroll-behavior: none` on html/body
- [ ] `-webkit-overflow-scrolling: touch` on overflow-auto regions
- [ ] Tap targets ≥ 38px minimum
- [ ] Apple meta tags for Add-to-Home-Screen
- [ ] Mobile layout uses drawer for secondary content

Each of these took me longer to find than to implement. The CSS is 20 lines total. The payoff is a web app that feels right.

---

**Proof in the wild:** the [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) applies all of the above. Open it on an iPhone, tap the Settings and Agents buttons, install an agent, chat. All of this just works now. Three days ago it didn't.
