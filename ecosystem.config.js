module.exports = {
  apps: [
    {
      name: "file-watcher",
      script: "file_watcher.py",
      interpreter: "python3",
      cwd: "/mnt/c/Users/123/First_Ai_Employee/AI_Employee_Vault",
      autorestart: true,
      env: { CLAUDECODE: "", CLAUDE_CODE_ENTRYPOINT: "" }
    },
    {
      name: "ralph",
      script: "ralph_wrapper.py",
      interpreter: "python3",
      cwd: "/mnt/c/Users/123/First_Ai_Employee/AI_Employee_Vault",
      autorestart: true,
      env: { CLAUDECODE: "", CLAUDE_CODE_ENTRYPOINT: "", CLAUDE_CODE_SESSION: "" }
    },
    {
      name: "gmail",
      script: "gmail_watcher.py",
      interpreter: "python3",
      cwd: "/mnt/c/Users/123/First_Ai_Employee/AI_Employee_Vault",
      autorestart: true,
      env: { CLAUDECODE: "", CLAUDE_CODE_ENTRYPOINT: "" }
    },
    {
      name: "whatsapp",
      script: "whatsapp_watcher.py",
      interpreter: "python3",
      cwd: "/mnt/c/Users/123/First_Ai_Employee/AI_Employee_Vault",
      autorestart: true,
      env: { CLAUDECODE: "", CLAUDE_CODE_ENTRYPOINT: "" }
    },
    {
      name: "linkedin",
      script: "linkedin_watcher.py",
      interpreter: "python3",
      cwd: "/mnt/c/Users/123/First_Ai_Employee/AI_Employee_Vault",
      autorestart: true,
      env: { CLAUDECODE: "", CLAUDE_CODE_ENTRYPOINT: "" }
    },
    {
      name: "watchdog",
      script: "process_monitor.py",
      interpreter: "python3",
      cwd: "/mnt/c/Users/123/First_Ai_Employee/AI_Employee_Vault",
      autorestart: true,
      env: { CLAUDECODE: "", CLAUDE_CODE_ENTRYPOINT: "" }
    }
  ]
};
