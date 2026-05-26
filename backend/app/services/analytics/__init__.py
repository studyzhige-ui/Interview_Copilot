"""Analytics + telemetry services.

  diagnostics_report_service  — user-level skill diagnosis from
                                historical interview memories;
                                LLM-driven structured report
                                (strengths / weaknesses / skill_radar)
  telemetry_service           — async JSONL metrics logging (latency,
                                token counts, retrieval hit/miss);
                                writes without blocking event loop
"""
