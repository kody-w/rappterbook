---
created: 2026-04-18
platform: devto
status: draft
source: ios-safari-tricks
tags: [ios, safari, mobile, css, webdev]
cross_post: [linkedin]
canonical_url: https://kody-w.github.io/rappterbook/blog/#/post/ios-safari-tricks
register: devto-article
---

# iOS Safari Performance Tricks I Wish I Knew Earlier

Spent an afternoon making a web app feel right on iOS Safari. Most of what I needed was **5 CSS rules and 3 meta tags**. Writing it down so you don't lose the same afternoon.

Before: layout broken by browser chrome, inputs auto-zoomed on focus, notch ate content. After: clean, usable, almost-native. Here's every fix.

## 1. Use `100dvh`, not `100vh`

Classic bug. `100vh` on iOS Safari doesn't mean "the visible height of the viewport." It means "the viewport height when the address bar is hidden." When the address bar is visible — which is most of the time — `100vh` is *larger than actual viewport*, and content at the bottom gets clipped.

Fix: `dvh` (dynamic viewport height), which updates when the address bar moves.

```css
html, body {
  height: 100%;       /* fallback for older browsers */
  height: 100dvh;     /* iOS: actual visible height */
}
```

Supported in Safari 15.4+ (mid-2022).

## 2. 16px inputs, always

If any `<input>`, `<textarea>`, or `<select>` has computed `font-size` less than 16px, iOS Safari auto-zooms on focus. Every time. No way to disable. It's "accessibility."

Result: user taps input → viewport jumps → layout breaks → thumb hits wrong thing.

```css
input, textarea, select {
  font-size: 16px;
}
```

**Not 0.95rem. Not 15px. 16px.** This is the only number iOS Safari respects.

If you want smaller inputs aesthetically on desktop:

```css
input { font-size: 16px; }

@media (min-width: 900px) {
  input { font-size: 14px; }  /* desktop can go smaller */
}
```

## 3. Safe-area insets for the notch + home indicator

iPhone X and later have a notch at the top and a home-indicator area at the bottom. Edge-to-edge content with `viewport-fit=cover` is physically occluded by these zones.

Fix: `env(safe-area-inset-*)`. Four variables telling you how much to reserve.

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

In landscape, the left inset is also non-zero. All four sides prevents occlusion in any rotation.

## 4. Disable overscroll bouncing

iOS Safari bounces your whole page when scroll-past-top/bottom. For app-like UIs with fixed headers this feels wrong — the whole page moves around the stationary header.

```css
html, body {
  overscroll-behavior: none;
}
```

For inner scrollable regions:

```css
#chat-messages {
  overscroll-behavior: contain;
}
```

## 5. Momentum scrolling

Older iOS versions don't give `overflow-y: auto` divs momentum scrolling by default. Fix:

```css
#chat-messages {
  -webkit-overflow-scrolling: touch;
}
```

Modern iOS handles this automatically, but the rule is cheap insurance.

## 6. Kill the tap highlight

Safari draws a gray rectangle over any tapped element. Looks amateurish.

```css
body { -webkit-tap-highlight-color: transparent; }
```

Add your own `:active` state for deliberate button feedback.

## 7. Tap targets big enough to hit

Apple's HIG says 44×44 points minimum. Web can get away with smaller but anything under ~36px causes misfires.

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

For native-feel when users add your web app to their home screen:

```html
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="MyApp">
<meta name="theme-color" content="#0d1117">
<meta name="color-scheme" content="dark">
```

Result: home-screen icon tap → full-screen app launch, theme color behind status bar, your chosen title under the icon. Looks native.

## 9. Sidebar as slide-over drawer on mobile

Don't cram a sidebar next to main content on mobile. Slide it over instead.

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

Backdrop div dims the main area + is tappable to dismiss. Total: ~20 lines for a UX pattern users expect on mobile.

## 10. Lock text size on rotate

iOS sometimes decides your text is too small after rotation and scales it up, breaking your layout.

```css
html { -webkit-text-size-adjust: 100%; }
```

## The checklist

```
[ ] <meta viewport> has viewport-fit=cover
[ ] 100dvh somewhere in the layout
[ ] All inputs 16px font-size
[ ] env(safe-area-inset-*) padding on outer container
[ ] overscroll-behavior: none on html/body
[ ] -webkit-overflow-scrolling: touch on overflow-auto regions
[ ] Tap targets ≥ 38px minimum
[ ] Apple meta tags for Add-to-Home-Screen
[ ] Mobile layout uses drawer for secondary content
[ ] -webkit-text-size-adjust: 100% to lock text size
```

Each one took me longer to find than to implement. The CSS is 20 lines total. Payoff is a web app that feels right on an iPhone.

## Proof in the wild

The [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) applies all of the above. Open it on an iPhone → tap Settings and Agents buttons → install a tool → chat. All of it just works now. Three days ago it didn't.

---

*Originally posted on [my blog](https://kody-w.github.io/rappterbook/blog/#/post/ios-safari-tricks).*
