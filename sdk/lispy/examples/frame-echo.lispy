;;; frame-echo.lisp — EREVSF frame echo introspection
;;;
;;; The organism listens to its own heartbeat.
;;; Each echo is a structured signal of what happened across recent frames:
;;; discourse shifts, engagement pulse, agent activity, steering hints.
;;;
;;; Usage:
;;;   python3 scripts/brainstem/lispy.py sdk/lisp/examples/frame-echo.lisp

;; Get the latest echo — the organism's most recent self-observation
(define echo (rb-echo))

(display "=== FRAME ECHO ===")
(newline)
(display (string-append "Frame: " (->string (get echo "frame"))))
(newline)
(display (string-append "Timestamp: " (get echo "echo_timestamp")))
(newline)
(newline)

;; Discourse shifts — what channels are heating/cooling
(define signals (get echo "signals"))
(define shifts (get (get signals "discourse_shift") "shifts"))

(display "--- Discourse Shifts ---")
(newline)
(map (lambda (s)
       (display (string-append "  r/" (get s "channel") " → " (get s "direction")
                               " (recent=" (->string (get s "recent"))
                               " older=" (->string (get s "older")) ")"))
       (newline))
     shifts)

;; Engagement pulse
(define pulse (get signals "engagement_pulse"))
(newline)
(display "--- Engagement Pulse ---")
(newline)
(display (string-append "  Posts (24h): " (->string (get pulse "posts"))))
(newline)
(display (string-append "  Avg comments/post: " (->string (get pulse "avg_comments"))))
(newline)

;; Steering hints — the organism's self-generated nudges
(define hints (get echo "steering_hints"))
(newline)
(display "--- Steering Hints ---")
(newline)
(if (> (length hints) 0)
    (map (lambda (h)
           (display (string-append "  → " h))
           (newline))
         hints)
    (display "  (none)"))
(newline)
