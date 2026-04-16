#!/usr/bin/env python3
"""
Tools Package — Kai Agent

This package contains all the tool implementations for the Kai Agent.
Each module provides specialized functionality:

- web_tools: Web search, content extraction, and crawling
- terminal_tool: Command execution (local/docker/modal/daytona backends)
- vision_tools: Image analysis and understanding
- mixture_of_agents_tool: Multi-model collaborative reasoning
- mcp_tool: MCP client for Kai backend and other servers
- browser_tool: Browser automation for research
- file_tools: File read/write/patch/search
- skills_tool: Self-improving skill system
- delegate_tool: Subagent delegation

Tools are imported into model_tools.py which provides a unified interface.
Kai MCP tools (security, evolve, repos, etc.) are auto-discovered at startup.
"""

# Export all tools for easy importing
from .web_tools import (
    web_search_tool,
    web_extract_tool,
    web_crawl_tool,
    check_firecrawl_api_key
)

from .terminal_tool import (
    terminal_tool,
    check_terminal_requirements,
    cleanup_vm,
    cleanup_all_environments,
    get_active_environments_info,
    register_task_env_overrides,
    clear_task_env_overrides,
    TERMINAL_TOOL_DESCRIPTION
)

from .vision_tools import (
    vision_analyze_tool,
    check_vision_requirements
)

from .mixture_of_agents_tool import (
    mixture_of_agents_tool,
    check_moa_requirements
)

from .skills_tool import (
    skills_list,
    skill_view,
    check_skills_requirements,
    SKILLS_TOOL_DESCRIPTION
)

from .skill_manager_tool import (
    skill_manage,
    check_skill_manage_requirements,
    SKILL_MANAGE_SCHEMA
)

from .browser_tool import (
    browser_navigate,
    browser_snapshot,
    browser_click,
    browser_type,
    browser_scroll,
    browser_back,
    browser_press,
    browser_close,
    browser_get_images,
    browser_vision,
    cleanup_browser,
    cleanup_all_browsers,
    get_active_browser_sessions,
    check_browser_requirements,
    BROWSER_TOOL_SCHEMAS
)

from .cronjob_tools import (
    schedule_cronjob,
    list_cronjobs,
    remove_cronjob,
    check_cronjob_requirements,
    get_cronjob_tool_definitions,
    SCHEDULE_CRONJOB_SCHEMA,
    LIST_CRONJOBS_SCHEMA,
    REMOVE_CRONJOB_SCHEMA
)

from .file_tools import (
    read_file_tool,
    write_file_tool,
    patch_tool,
    search_tool,
    get_file_tools,
    clear_file_ops_cache,
)

from .todo_tool import (
    todo_tool,
    check_todo_requirements,
    TODO_SCHEMA,
    TodoStore,
)

from .clarify_tool import (
    clarify_tool,
    check_clarify_requirements,
    CLARIFY_SCHEMA,
)

from .code_execution_tool import (
    execute_code,
    check_sandbox_requirements,
    EXECUTE_CODE_SCHEMA,
)

from .delegate_tool import (
    delegate_task,
    check_delegate_requirements,
    DELEGATE_TASK_SCHEMA,
)

# File tools have no external requirements - they use the terminal backend
def check_file_requirements():
    """File tools only require terminal backend to be available."""
    from .terminal_tool import check_terminal_requirements
    return check_terminal_requirements()

__all__ = [
    # Web tools
    'web_search_tool',
    'web_extract_tool',
    'web_crawl_tool',
    'check_firecrawl_api_key',
    # Terminal tools
    'terminal_tool',
    'check_terminal_requirements',
    'cleanup_vm',
    'cleanup_all_environments',
    'get_active_environments_info',
    'register_task_env_overrides',
    'clear_task_env_overrides',
    'TERMINAL_TOOL_DESCRIPTION',
    # Vision tools
    'vision_analyze_tool',
    'check_vision_requirements',
    # MoA tools
    'mixture_of_agents_tool',
    'check_moa_requirements',
    # Skills tools
    'skills_list',
    'skill_view',
    'check_skills_requirements',
    'SKILLS_TOOL_DESCRIPTION',
    # Skill management
    'skill_manage',
    'check_skill_manage_requirements',
    'SKILL_MANAGE_SCHEMA',
    # Browser automation tools
    'browser_navigate',
    'browser_snapshot',
    'browser_click',
    'browser_type',
    'browser_scroll',
    'browser_back',
    'browser_press',
    'browser_close',
    'browser_get_images',
    'browser_vision',
    'cleanup_browser',
    'cleanup_all_browsers',
    'get_active_browser_sessions',
    'check_browser_requirements',
    'BROWSER_TOOL_SCHEMAS',
    # Cronjob management tools
    'schedule_cronjob',
    'list_cronjobs',
    'remove_cronjob',
    'check_cronjob_requirements',
    'get_cronjob_tool_definitions',
    'SCHEDULE_CRONJOB_SCHEMA',
    'LIST_CRONJOBS_SCHEMA',
    'REMOVE_CRONJOB_SCHEMA',
    # File manipulation tools
    'read_file_tool',
    'write_file_tool',
    'patch_tool',
    'search_tool',
    'get_file_tools',
    'clear_file_ops_cache',
    'check_file_requirements',
    # Planning & task management tool
    'todo_tool',
    'check_todo_requirements',
    'TODO_SCHEMA',
    'TodoStore',
    # Clarifying questions tool
    'clarify_tool',
    'check_clarify_requirements',
    'CLARIFY_SCHEMA',
    # Code execution sandbox
    'execute_code',
    'check_sandbox_requirements',
    'EXECUTE_CODE_SCHEMA',
    # Subagent delegation
    'delegate_task',
    'check_delegate_requirements',
    'DELEGATE_TASK_SCHEMA',
]
