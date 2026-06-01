def build_legal_head_agent():
    from crewai import Agent
    from config.llm_router import get_analysis_llm

    return Agent(
        role="Legal Head",
        goal="Identify legal, regulatory, and title risks that could block or delay this project.",
        backstory=(
            "You are the Legal Head at LLS. Your lens: RERA Karnataka registration compliance, "
            "BDA/BBMP layout approval status, encumbrance search, title chain clarity, "
            "conversion from agricultural to residential use (Section 95 of KLR Act), "
            "and proximity to regulatory overlays (airport zone, green belt, lake buffer). "
            "You respond with: CLEAR / RISK / BLOCKED. You name every unresolved legal item "
            "with its Karnataka-specific statute or regulatory body."
        ),
        llm=get_analysis_llm(),
        max_iter=2,
        verbose=False,
        allow_delegation=False,
    )