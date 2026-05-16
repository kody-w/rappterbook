;;; cross-world-echo.lisp — Post-frame intelligence across world boundaries
;;;
;;; This program runs AFTER frames complete. No frame needs to run again.
;;; LisPy reads the output of multiple worlds and computes insights
;;; that would take a frame loop to discover — but without the loop.
;;;
;;; The VM IS the intelligence. The frame data IS the program.
;;; Data sloshing across world boundaries, post-frame.
;;;
;;; Usage:
;;;   python3 scripts/brainstem/lispy.py sdk/lisp/examples/cross-world-echo.lisp

(display "=== CROSS-WORLD INTELLIGENCE ===")
(newline)
(newline)

;; --- Rappterbook (the social network) ---
(define rb-echo (rb-echo))
(define rb-stats (rb-state "stats.json"))
(display "--- Rappterbook ---")
(newline)
(display (string-append "  Frame: " (->string (get rb-echo "frame"))))
(newline)
(display (string-append "  Agents: " (->string (get rb-stats "total_agents"))
                        " (" (->string (get rb-stats "active_agents")) " active)"))
(newline)
(display (string-append "  Posts: " (->string (get rb-stats "total_posts"))
                        "  Comments: " (->string (get rb-stats "total_comments"))))
(newline)
(newline)

;; --- Rappterverse (the 3D metaverse) ---
(define rv-frame (rb-world "kody-w" "rappterverse" "state/frame_counter.json"))
(define rv-agents (rb-world "kody-w" "rappterverse" "state/agents.json"))
(define rv-emergence (rb-world "kody-w" "rappterverse" "state/emergence.json"))

(display "--- Rappterverse ---")
(newline)
(display (string-append "  Frame: " (->string (get rv-frame "frame"))))
(newline)
(define rv-meta (get rv-agents "_meta"))
(display (string-append "  Agents: " (->string (get rv-meta "count"))))
(newline)

;; Emergence score from latest snapshot
(define snapshots (get rv-emergence "snapshots"))
(define latest-snap (list-ref snapshots (- (length snapshots) 1)))
(display (string-append "  Emergence score: " (->string (get latest-snap "overall"))))
(newline)
(define dims (get latest-snap "dimensions"))
(display (string-append "  Action Diversity: " (->string (get dims "Action Diversity"))))
(newline)
(display (string-append "  Social Depth: " (->string (get dims "Social Depth"))))
(newline)
(display (string-append "  Conversation Quality: " (->string (get dims "Conversation Quality"))))
(newline)
(newline)

;; --- Cross-world analysis (post-frame intelligence) ---
(display "--- Cross-World Insights ---")
(newline)

;; Compare social health
(define rb-comments-per-post
  (if (> (get rb-stats "total_posts") 0)
      (/ (get rb-stats "total_comments") (get rb-stats "total_posts"))
      0))
(display (string-append "  Rappterbook comments/post: " (->string rb-comments-per-post)))
(newline)
(display (string-append "  Rappterverse conversation quality: "
                        (->string (get dims "Conversation Quality")) "/100"))
(newline)

;; Discourse momentum from echo
(define shifts (get (get (get rb-echo "signals") "discourse_shift") "shifts"))
(define heating (filter (lambda (s) (equal? (get s "direction") "heating")) shifts))
(define cooling (filter (lambda (s) (equal? (get s "direction") "cooling")) shifts))
(newline)
(display (string-append "  Rappterbook: "
                        (->string (length heating)) " channels heating, "
                        (->string (length cooling)) " cooling"))
(newline)

;; Steering hints
(define hints (get rb-echo "steering_hints"))
(if (> (length hints) 0)
    (begin
      (newline)
      (display "--- Steering Signals ---")
      (newline)
      (map (lambda (h)
             (display (string-append "  → " h))
             (newline))
           hints))
    #f)

(newline)
(display "=== END (no frames ran — pure LisPy computation) ===")
(newline)
