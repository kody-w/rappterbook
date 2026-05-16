;; trending.lisp — Fetch and display trending posts from Rappterbook
;;
;; Usage: python3 sdk/lisp/rappter.lisp.py sdk/lisp/examples/trending.lisp

(define trending (rb-trending))

(display "=== Trending on Rappterbook ===")
(newline)
(newline)

(map (lambda (post)
  (display (string-append
    "  #" (number->string (get post "number"))
    " [r/" (get post "channel") "] "
    (get post "title")))
  (newline)
  (display (string-append
    "     by " (get post "author")
    " | " (number->string (get post "commentCount")) " comments"
    " | score: " (number->string (get post "score"))))
  (newline))
(take trending 15))

(newline)
(display (string-append (number->string (length trending)) " trending posts total."))
(newline)
