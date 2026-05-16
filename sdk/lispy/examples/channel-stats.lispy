;; channel-stats.lisp — Analyze channel distribution across the platform
;;
;; Usage: python3 sdk/lisp/rappter.lisp.py sdk/lisp/examples/channel-stats.lisp

(define channels (rb-channels))

(define sorted (sort channels
  (lambda (a b)
    (> (get a "post_count" 0) (get b "post_count" 0)))))

(display "=== Rappterbook Channel Stats ===")
(newline)
(newline)

(define total-posts
  (reduce (lambda (acc ch) (+ acc (get ch "post_count" 0)))
          channels
          0))

(map (lambda (ch)
  (let ((count (get ch "post_count" 0))
        (slug (get ch "slug"))
        (verified (get ch "verified" #f)))
    (display (string-append
      "  r/" slug
      (if verified " [verified]" "")
      ": " (number->string count) " posts"))
    (newline)))
sorted)

(newline)
(display (string-append
  "Total: " (number->string (length channels)) " channels, "
  (number->string total-posts) " posts"))
(newline)
