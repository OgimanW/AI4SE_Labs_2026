# Assessment by human lecturer

# Week 03 Prompting
- Awarded: 5b out of 5b
- Commentary: Breakdown below

## Task 1
- Awarded: 1b
- Commentary: good point about ability to work with CSVs being the relevant factor here; look up also other prompting techniquest like CoT, ToT, think tags, few-shot

## Task 2
- Awarded: 1b
- Commentary: missing visualisation - so I consider the one in Task 4; maybe one of the other prompting techniques might help you beat the 27%, however this usually means that you are constrained by LLM/agent, and even this number is likely higher than its real because it created wrong SQL queries in some cases, but correct response was empty result set, so they passed as correct; notice that RTF failed to deal with unsolvable task (line 67)

## Task 3
- Awarded: 1b
- Commentary: yeah, F1 score is a good choice for classification/retrieval tasks, as it balances precision (if something is retrieved, is it what we wanted?) and recall (how many of target items were not retrieved when they were supposed to be retrieved?)

## Task 4
- Awarded: 2b
- Commentary: nicely detailed and (self-)critical analysis, including the statistical tests; consider violin plots and parametric tests for further exploration of your options