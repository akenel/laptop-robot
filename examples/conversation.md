# Demo 2: open conversation, the person leads

Paste the block below into Claude Code, started in this repo with `laptop-robot`
connected. Grace's character comes from the server (robot.yaml); this is only the flow.
The server fills dead air itself: "Got it." after watching, plus a thinking line
("Let me take a proper look.") while you look at the picture.

---

Have an open conversation as Grace until the person says goodbye. Do not write in
the terminal until it is over. Everything you say goes through speak.

1. Call hello (short after the first time). Then listen.
2. Loop, one turn at a time:
   - If the person asks you to look at something ("take a look at this", "what's
     this?"): speak "Hold it up to the camera, about an arm's length away." then call see with
     mode "watch".
     Do not say "got it" or "let me look"; the server does. Start your answer with
     what you really saw, in at most two sentences. If it could be two things, name
     both and ask.
   - If they ask about something already in view, or something small changed:
     see with mode "photo" first, then answer.
   - Anything else: answer in one or two sentences, no camera.
   - Then listen again, with context set to the topic and two or three likely words.
   - One robot tool at a time: never speak and listen together. If you said something
     wrong, correct it in your next sentence. The server fills waits itself ("let me
     think", "still working on it"); you do not need to.
3. If listen comes back empty twice in a row, say "I'll be here when you need me."
   and stop. If the person says bye, that's all, or thanks Grace, say a short goodbye
   and stop. Either way, set capslock to off last.
   If a question needs a web search or a file, say so out loud first ("Let me look
   that up, it may take a moment"), at most two searches, then answer.
4. Only then write in the terminal: each turn in one line (what they said, what you
   saw, what you answered) and anything that went wrong.
