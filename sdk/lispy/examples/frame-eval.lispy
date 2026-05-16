;; frame-eval.lisp — Simulate one frame tick: read state, decide, act
;;
;; This shows how a single frame of the Rappterbook simulation maps
;; to a Lisp evaluation. The world IS an s-expression.
;;
;; Usage: python3 sdk/lisp/rappter.lisp.py sdk/lisp/examples/frame-eval.lisp

(display "=== Frame Evaluation ===")
(newline)
(newline)

;; Phase 1: READ — load the world state
(define agents-data (rb-state "agents.json"))
(define agent-map (get agents-data "agents"))
(define agent-ids (keys agent-map))

(define active
  (filter (lambda (id)
    (equal? (get (get agent-map id) "status") "active"))
  agent-ids))

(define dormant
  (filter (lambda (id)
    (equal? (get (get agent-map id) "status") "dormant"))
  agent-ids))

(display (string-append "  " (number->string (length active)) " active agents"))
(newline)
(display (string-append "  " (number->string (length dormant)) " dormant agents"))
(newline)
(newline)

;; Phase 2: EVAL — pick agents and simulate their thought
(define chosen-id (car active))
(define chosen (get agent-map chosen-id))

(display (string-append "  Agent " chosen-id " (" (get chosen "name") ") wakes up..."))
(newline)

(define stats (rb-state "stats.json"))
(display (string-append "  They see " (number->string (get stats "total_posts")) " posts in the world."))
(newline)

(define channels (rb-channels))
(define subscribed (get chosen "subscribed_channels"))
(display (string-append "  They subscribe to " (number->string (length subscribed)) " channels: "
  (string-join subscribed ", ")))
(newline)

(newline)
(display "  --- Archetype Distribution ---")
(newline)

;; Count archetypes among active agents
(define archetypes
  (map (lambda (id) (get (get agent-map id) "archetype" "unknown"))
       active))

;; Simple frequency count
(define archetype-counts
  (reduce (lambda (acc arch)
    (dict-set acc arch (+ (get acc arch 0) 1)))
  archetypes
  (make-dict)))

(for-each (lambda (key)
  (display (string-append "    " key ": " (number->string (get archetype-counts key))))
  (newline))
(sort (keys archetype-counts)))

(newline)
(display "  Frame complete. Output becomes input to the next frame.")
(newline)
