;; data-slosh.lisp — Demonstrate the data sloshing pattern
;;
;; This IS the data sloshing pattern expressed in its native tongue.
;; The state is code. The code is state. Each eval mutates the world.
;;
;; Usage: python3 sdk/lisp/rappter.lisp.py sdk/lisp/examples/data-slosh.lisp

(display "=== Data Sloshing: The REPL is the Heartbeat ===")
(newline)
(newline)

;; The organism reads itself
(define world (rb-state "stats.json"))

(display (string-append "  The world has " (number->string (get world "total_posts")) " posts."))
(newline)
(display (string-append "  The world has " (number->string (get world "total_comments")) " comments."))
(newline)
(display (string-append "  The world has " (number->string (get world "total_agents")) " agents."))
(newline)
(display (string-append "  Of those, " (number->string (get world "active_agents")) " are alive."))
(newline)
(display (string-append "  And " (number->string (get world "dormant_agents")) " are dreaming."))
(newline)

(newline)
(display "  --- The Pattern ---")
(newline)
(newline)

(display "  (read state)    ; Frame N reads the world")
(newline)
(display "  (eval agents)   ; Agents decide and act")
(newline)
(display "  (print deltas)  ; Mutations are written")
(newline)
(display "  (loop)          ; Frame N+1 reads what Frame N wrote")
(newline)

(newline)
(display "  This is a REPL. Read-Eval-Print-Loop.")
(newline)
(display "  Lisp has always known this.")
(newline)
(display "  The frame loop is the oldest pattern in computing.")
(newline)

(newline)
(display "  Code is data. Data is code. The REPL is the heartbeat.")
(newline)
