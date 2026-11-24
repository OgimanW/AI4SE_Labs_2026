# Assessment by laguna-s-2.1

# Week 03 Prompting
- Awarded: 3.5b out of 5b
- Commentary: The student produced solid work across all four tasks. Three prompt files (CO-STAR, RTF, RACE) are well-structured and appropriate for the Text-to-SQL task, with CO-STAR being particularly thorough. Predictions for 155 questions per prompt are well-formatted with proper CSV escaping and session metadata. The F1 metric implementation in Task 3 is excellent, with detailed per-question and summary CSV outputs plus a thorough report. The Task 4 report was submitted as a PDF that could not be read, limiting verification of its content. Reports are brief and written in Slovak, and the Task 2 report is missing the requested visualization.

## Task 1
- Awarded: 0.75b   (max 1b)
- Commentary: The student chose three prompting frameworks from frompting.com: CO-STAR, RTF, and RACE. The CO-STAR prompt is excellent, clearly following the CO-STAR framework structure (Context, Objective, Style, Tone, Audience, Response format). The RTF prompt follows Role/Task/Format well. The RACE prompt, while functional, does not clearly follow the RACE framework structure (Role/Action/Context/Expectation) and resembles RTF with different headings. A brief report (OUTPUT.md) explains the choices and cites frompting.com as the source. The report is very brief and does not fully elaborate on expectations from each prompt, but the core deliverables (3 formulated prompts + explanation + source citation) are present.

## Task 2
- Awarded: 0.75b   (max 1b)
- Commentary: Three prediction CSV files (CO-STAR, RTF, RACE) were produced, each containing 155 SQL predictions with proper CSV escaping (quoting fields with commas). The Output.txt file records inference times (32 steps/3m5s, 49 steps/10m50s, 21 steps/3m45s) and accuracy per prompt (43/155, 27/155, 43/155). Separate sessions were used per prompt as hinted. However, the brief report in Output.txt is minimal and does not include the "nice visualization" explicitly requested by the task. The predictions and timing data are well-organized with model and prompt identification metadata.

## Task 3
- Awarded: 1b   (max 1b)
- Commentary: The student proposed macro-F1 as an alternative metric to exact accuracy, arguing that it provides partial credit when some (but not all) predicted rows match expected results. The metric implementation (calculate_f1.py) is well-structured, treating result rows as multisets and computing precision, recall, and F1 per question, then macro-averaging. The report (REPORT.md) thoroughly explains why F1 complements (does not replace) the original exact-match metric. CSV outputs (f1_results.csv, f1_per_question.csv) provide summary and per-question breakdowns. Results: CO-STAR 0.2774, RTF 0.1742, RACE 0.2774. This is a strong, complete submission.

## Task 4
- Awarded: 1b   (max 2b)
- Commentary: The Task 4 deliverable was submitted as a PDF (Task_4_Report.pdf) which could not be read by the available tools, limiting verification of its content. The task requires a detailed analysis with tables, graphs, statistical significance testing, and interpretation considering prompts, model, and coding agent as factors. The underlying data from Tasks 2 and 3 is thorough and well-structured, showing CO-STAR and RACE outperformed RTF (0.2774 vs 0.1742 F1), with RTF taking nearly 3x longer. The PDF report deliverable exists, but its content could not be verified to confirm the presence of required statistical analysis, visualizations, and interpretation.
