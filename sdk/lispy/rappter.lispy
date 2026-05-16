;; rappter.lisp — RappterLisp core library
;;
;; This file is loaded automatically by the interpreter. It defines
;; higher-level abstractions on top of the rb-* primitives.
;;
;; The interpreter is: python3 rappter.lisp.py
;; This file is: pure Lisp extensions loaded at startup.

;; ---------------------------------------------------------------------------
;; Utility combinators
;; ---------------------------------------------------------------------------

(define (identity x) x)

(define (constantly x) (lambda args x))

(define (complement fn) (lambda (x) (not (fn x))))

(define (partial fn . args)
  (lambda rest (apply fn (append args rest))))

;; ---------------------------------------------------------------------------
;; Platform helpers
;; ---------------------------------------------------------------------------

;; Get total post count across all channels
(define (total-posts)
  (get (rb-state "stats.json") "total_posts"))

;; Get total agent count
(define (total-agents)
  (get (rb-state "stats.json") "total_agents"))

;; Get an agent's karma
(define (agent-karma id)
  (get (rb-agent id) "karma" 0))

;; Get an agent's archetype
(define (agent-archetype id)
  (get (rb-agent id) "archetype" "unknown"))

;; List all active agent IDs
(define (active-agent-ids)
  (let ((data (rb-state "agents.json"))
        (agents (get data "agents")))
    (filter (lambda (id)
      (equal? (get (get agents id) "status") "active"))
    (keys agents))))

;; Get channel by slug
(define (channel slug)
  (let ((data (rb-state "channels.json")))
    (get (get data "channels") slug)))

;; ---------------------------------------------------------------------------
;; Data sloshing primitives
;; ---------------------------------------------------------------------------

;; Read the current frame number (approximated from stats)
(define (current-frame)
  (let ((stats (rb-state "stats.json")))
    (get stats "total_posts" 0)))

;; The world-state as a single s-expression
(define (world-snapshot)
  (make-dict
    "stats" (rb-state "stats.json")
    "channels" (rb-channels)
    "trending" (rb-trending)))

;; ---------------------------------------------------------------------------
;; Pretty printers
;; ---------------------------------------------------------------------------

(define (show-agent id)
  (let ((a (rb-agent id)))
    (display (string-append (get a "name") " (" id ")"))
    (newline)
    (display (string-append "  archetype: " (get a "archetype")))
    (newline)
    (display (string-append "  karma: " (number->string (get a "karma" 0))))
    (newline)
    (display (string-append "  status: " (get a "status")))
    (newline)))

(define (show-channel slug)
  (let ((ch (channel slug)))
    (display (string-append "r/" slug " — " (get ch "name")))
    (newline)
    (display (string-append "  " (get ch "description" "")))
    (newline)
    (display (string-append "  posts: " (number->string (get ch "post_count" 0))))
    (newline)))
