"""
Ansible Operations Skill — Validate, generate, explain, improve, and reference
Ansible playbooks and modules.

Each function is a standalone action handler invoked by the SkillsManager
or registered as an internal handler in skill_executor.py.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False
    logger.debug("PyYAML not available — Ansible validation will use regex fallback")


# ---------------------------------------------------------------------------
# Module Reference — Top 60 Ansible modules with syntax and examples
# ---------------------------------------------------------------------------

ANSIBLE_MODULES: Dict[str, Dict[str, str]] = {
    "copy": {
        "description": "Copy files to remote locations",
        "syntax": "copy: src=<local> dest=<remote> [owner=<user>] [group=<grp>] [mode=<perm>]",
        "example": "- copy:\n    src: files/app.conf\n    dest: /etc/app/app.conf\n    owner: root\n    mode: '0644'",
    },
    "template": {
        "description": "Template a file out to a remote host using Jinja2",
        "syntax": "template: src=<template.j2> dest=<remote> [owner=<user>] [mode=<perm>]",
        "example": "- template:\n    src: templates/nginx.conf.j2\n    dest: /etc/nginx/nginx.conf\n    notify: restart nginx",
    },
    "file": {
        "description": "Manage file and directory properties",
        "syntax": "file: path=<path> state=<file|directory|link|absent> [owner=<user>] [mode=<perm>]",
        "example": "- file:\n    path: /opt/app/logs\n    state: directory\n    owner: appuser\n    mode: '0755'",
    },
    "service": {
        "description": "Manage services (start, stop, restart, enable)",
        "syntax": "service: name=<svc> state=<started|stopped|restarted|reloaded> [enabled=yes|no]",
        "example": "- service:\n    name: nginx\n    state: started\n    enabled: yes",
    },
    "systemd": {
        "description": "Manage systemd units",
        "syntax": "systemd: name=<unit> state=<started|stopped|restarted|reloaded> [enabled=yes|no] [daemon_reload=yes]",
        "example": "- systemd:\n    name: myapp.service\n    state: restarted\n    daemon_reload: yes",
    },
    "user": {
        "description": "Manage user accounts",
        "syntax": "user: name=<user> [state=present|absent] [groups=<grp>] [shell=<sh>] [create_home=yes]",
        "example": "- user:\n    name: deploy\n    groups: docker,sudo\n    shell: /bin/bash\n    create_home: yes",
    },
    "group": {
        "description": "Manage groups",
        "syntax": "group: name=<grp> [state=present|absent] [gid=<id>]",
        "example": "- group:\n    name: appgroup\n    state: present",
    },
    "apt": {
        "description": "Manage apt packages (Debian/Ubuntu)",
        "syntax": "apt: name=<pkg> [state=present|absent|latest] [update_cache=yes]",
        "example": "- apt:\n    name: nginx\n    state: latest\n    update_cache: yes",
    },
    "yum": {
        "description": "Manage yum packages (RHEL/CentOS)",
        "syntax": "yum: name=<pkg> [state=present|absent|latest]",
        "example": "- yum:\n    name: httpd\n    state: present",
    },
    "dnf": {
        "description": "Manage dnf packages (Fedora/RHEL 8+)",
        "syntax": "dnf: name=<pkg> [state=present|absent|latest]",
        "example": "- dnf:\n    name: podman\n    state: latest",
    },
    "pip": {
        "description": "Manage Python packages via pip",
        "syntax": "pip: name=<pkg> [version=<ver>] [virtualenv=<path>] [state=present|absent|latest]",
        "example": "- pip:\n    name: flask\n    version: '2.3.0'\n    virtualenv: /opt/app/venv",
    },
    "cron": {
        "description": "Manage cron jobs",
        "syntax": "cron: name=<name> [minute=<m>] [hour=<h>] [job=<cmd>] [state=present|absent]",
        "example": "- cron:\n    name: backup\n    minute: '0'\n    hour: '2'\n    job: /opt/scripts/backup.sh",
    },
    "command": {
        "description": "Execute commands on targets (no shell processing)",
        "syntax": "command: <cmd> [creates=<file>] [removes=<file>] [chdir=<dir>]",
        "example": "- command: /opt/app/migrate.sh\n  args:\n    chdir: /opt/app\n    creates: /opt/app/.migrated",
    },
    "shell": {
        "description": "Execute shell commands (supports pipes, redirects)",
        "syntax": "shell: <cmd> [creates=<file>] [executable=<shell>]",
        "example": "- shell: cat /var/log/syslog | grep ERROR | wc -l\n  register: error_count\n  changed_when: false",
    },
    "raw": {
        "description": "Execute raw command without Python on target",
        "syntax": "raw: <cmd>",
        "example": "- raw: apt-get install -y python3\n  become: yes",
    },
    "script": {
        "description": "Transfer and execute a local script on remote",
        "syntax": "script: <local_script> [creates=<file>]",
        "example": "- script: scripts/setup.sh\n  args:\n    creates: /opt/app/.setup_done",
    },
    "lineinfile": {
        "description": "Manage lines in text files",
        "syntax": "lineinfile: path=<file> [regexp=<re>] line=<text> [state=present|absent] [insertafter=<re>]",
        "example": "- lineinfile:\n    path: /etc/hosts\n    regexp: '^127\\.0\\.0\\.1'\n    line: '127.0.0.1 localhost myhost'",
    },
    "blockinfile": {
        "description": "Insert/update/remove a block of text in a file",
        "syntax": "blockinfile: path=<file> block=<text> [marker=<str>] [state=present|absent]",
        "example": "- blockinfile:\n    path: /etc/ssh/sshd_config\n    block: |\n      Match Group sftp\n        ForceCommand internal-sftp",
    },
    "replace": {
        "description": "Replace all occurrences of a regex pattern in a file",
        "syntax": "replace: path=<file> regexp=<re> replace=<text>",
        "example": "- replace:\n    path: /etc/myapp/config.ini\n    regexp: 'DEBUG = true'\n    replace: 'DEBUG = false'",
    },
    "stat": {
        "description": "Retrieve file or filesystem status",
        "syntax": "stat: path=<path>",
        "example": "- stat:\n    path: /opt/app/data\n  register: app_data\n- debug:\n    msg: 'Exists'\n  when: app_data.stat.exists",
    },
    "find": {
        "description": "Find files matching criteria",
        "syntax": "find: paths=<dir> [patterns=<glob>] [age=<time>] [recurse=yes]",
        "example": "- find:\n    paths: /var/log\n    patterns: '*.log'\n    age: 7d\n  register: old_logs",
    },
    "archive": {
        "description": "Create compressed archives",
        "syntax": "archive: path=<src> dest=<archive> [format=gz|bz2|xz|zip]",
        "example": "- archive:\n    path: /opt/app/data\n    dest: /backups/data.tar.gz\n    format: gz",
    },
    "unarchive": {
        "description": "Unpack compressed archives",
        "syntax": "unarchive: src=<archive> dest=<dir> [remote_src=yes]",
        "example": "- unarchive:\n    src: https://example.com/app.tar.gz\n    dest: /opt/app\n    remote_src: yes",
    },
    "uri": {
        "description": "Interact with HTTP/HTTPS endpoints",
        "syntax": "uri: url=<url> [method=GET|POST|PUT|DELETE] [body=<data>] [return_content=yes]",
        "example": "- uri:\n    url: http://localhost:8080/health\n    method: GET\n    status_code: 200\n  register: health",
    },
    "get_url": {
        "description": "Download files from HTTP/HTTPS/FTP",
        "syntax": "get_url: url=<url> dest=<path> [checksum=<algo:hash>]",
        "example": "- get_url:\n    url: https://releases.example.com/app-1.0.tar.gz\n    dest: /tmp/app.tar.gz\n    checksum: sha256:abc123...",
    },
    "git": {
        "description": "Deploy software via git checkout",
        "syntax": "git: repo=<url> dest=<path> [version=<branch|tag>] [force=yes]",
        "example": "- git:\n    repo: https://github.com/org/app.git\n    dest: /opt/app\n    version: main",
    },
    "docker_container": {
        "description": "Manage Docker containers",
        "syntax": "docker_container: name=<name> image=<img> [state=started|stopped|absent] [ports=<list>]",
        "example": "- docker_container:\n    name: myapp\n    image: myapp:latest\n    state: started\n    ports:\n      - '8080:80'",
    },
    "docker_image": {
        "description": "Manage Docker images",
        "syntax": "docker_image: name=<name> [tag=<tag>] [source=pull|build|load] [build.path=<dir>]",
        "example": "- docker_image:\n    name: myapp\n    tag: latest\n    source: build\n    build:\n      path: /opt/app",
    },
    "firewalld": {
        "description": "Manage firewalld rules",
        "syntax": "firewalld: [port=<port/proto>] [service=<svc>] [permanent=yes] [state=enabled|disabled]",
        "example": "- firewalld:\n    port: 8080/tcp\n    permanent: yes\n    state: enabled\n    immediate: yes",
    },
    "ufw": {
        "description": "Manage UFW firewall rules",
        "syntax": "ufw: rule=<allow|deny|reject> [port=<port>] [proto=<tcp|udp>]",
        "example": "- ufw:\n    rule: allow\n    port: '443'\n    proto: tcp",
    },
    "sysctl": {
        "description": "Manage sysctl kernel parameters",
        "syntax": "sysctl: name=<param> value=<val> [state=present] [reload=yes]",
        "example": "- sysctl:\n    name: net.ipv4.ip_forward\n    value: '1'\n    sysctl_set: yes",
    },
    "mount": {
        "description": "Manage filesystem mounts",
        "syntax": "mount: path=<mount> src=<device> fstype=<type> state=<mounted|unmounted|absent|present>",
        "example": "- mount:\n    path: /mnt/data\n    src: /dev/sdb1\n    fstype: ext4\n    state: mounted",
    },
    "debug": {
        "description": "Print statements during execution",
        "syntax": "debug: [msg=<text>] [var=<variable>]",
        "example": "- debug:\n    msg: 'Deploy version {{ app_version }} complete'",
    },
    "assert": {
        "description": "Assert given expressions are true",
        "syntax": "assert: that=<list_of_conditions> [fail_msg=<text>]",
        "example": "- assert:\n    that:\n      - app_version is defined\n      - app_version | length > 0\n    fail_msg: 'app_version must be set'",
    },
    "wait_for": {
        "description": "Wait for a condition before continuing",
        "syntax": "wait_for: [port=<port>] [host=<host>] [delay=<sec>] [timeout=<sec>] [state=started|stopped]",
        "example": "- wait_for:\n    port: 8080\n    host: localhost\n    delay: 5\n    timeout: 60",
    },
    "set_fact": {
        "description": "Set host facts from a task",
        "syntax": "set_fact: <key>=<value>",
        "example": "- set_fact:\n    deploy_timestamp: \"{{ ansible_date_time.iso8601 }}\"\n    app_url: \"http://{{ ansible_hostname }}:8080\"",
    },
    "include_tasks": {
        "description": "Dynamically include a task file",
        "syntax": "include_tasks: <file.yml> [when=<condition>]",
        "example": "- include_tasks: setup_{{ ansible_os_family | lower }}.yml",
    },
    "include_role": {
        "description": "Dynamically include a role",
        "syntax": "include_role: name=<role> [tasks_from=<file>]",
        "example": "- include_role:\n    name: common\n    tasks_from: security.yml",
    },
    "import_tasks": {
        "description": "Statically import a task file",
        "syntax": "import_tasks: <file.yml>",
        "example": "- import_tasks: common/prerequisites.yml",
    },
    "import_role": {
        "description": "Statically import a role",
        "syntax": "import_role: name=<role>",
        "example": "- import_role:\n    name: nginx",
    },
    "ansible.builtin.setup": {
        "description": "Gather facts about remote hosts",
        "syntax": "setup: [filter=<pattern>] [gather_subset=<list>]",
        "example": "- setup:\n    filter: ansible_distribution*",
    },
    "package": {
        "description": "Generic OS package manager (auto-detects apt/yum/dnf)",
        "syntax": "package: name=<pkg> state=<present|absent|latest>",
        "example": "- package:\n    name: curl\n    state: present",
    },
    "hostname": {
        "description": "Manage hostname",
        "syntax": "hostname: name=<name>",
        "example": "- hostname:\n    name: webserver01.example.com",
    },
    "timezone": {
        "description": "Set system timezone",
        "syntax": "timezone: name=<tz>",
        "example": "- timezone:\n    name: America/New_York",
    },
    "authorized_key": {
        "description": "Manage SSH authorized keys",
        "syntax": "authorized_key: user=<user> key=<pubkey> [state=present|absent]",
        "example": "- authorized_key:\n    user: deploy\n    key: \"{{ lookup('file', 'keys/deploy.pub') }}\"",
    },
    "known_hosts": {
        "description": "Manage SSH known_hosts",
        "syntax": "known_hosts: name=<host> key=<hostkey> [state=present|absent]",
        "example": "- known_hosts:\n    name: github.com\n    key: \"{{ lookup('pipe', 'ssh-keyscan github.com') }}\"",
    },
    "mysql_db": {
        "description": "Manage MySQL databases",
        "syntax": "mysql_db: name=<db> [state=present|absent|dump|import] [login_host=<h>]",
        "example": "- mysql_db:\n    name: myapp\n    state: present\n    login_host: localhost",
    },
    "postgresql_db": {
        "description": "Manage PostgreSQL databases",
        "syntax": "postgresql_db: name=<db> [state=present|absent] [owner=<user>]",
        "example": "- postgresql_db:\n    name: myapp\n    owner: appuser\n    state: present",
    },
    "postgresql_user": {
        "description": "Manage PostgreSQL users/roles",
        "syntax": "postgresql_user: name=<user> [password=<pw>] [db=<db>] [priv=<priv>]",
        "example": "- postgresql_user:\n    name: appuser\n    password: \"{{ db_password }}\"\n    db: myapp\n    priv: ALL",
    },
    "synchronize": {
        "description": "Wrapper around rsync for file sync",
        "syntax": "synchronize: src=<local> dest=<remote> [delete=yes] [recursive=yes]",
        "example": "- synchronize:\n    src: /opt/app/dist/\n    dest: /var/www/html/\n    delete: yes",
    },
    "fetch": {
        "description": "Fetch files from remote nodes",
        "syntax": "fetch: src=<remote> dest=<local> [flat=yes]",
        "example": "- fetch:\n    src: /var/log/app.log\n    dest: /tmp/logs/\n    flat: yes",
    },
    "pause": {
        "description": "Pause playbook execution",
        "syntax": "pause: [seconds=<n>] [minutes=<n>] [prompt=<text>]",
        "example": "- pause:\n    seconds: 30\n    prompt: 'Waiting for service to stabilize'",
    },
    "fail": {
        "description": "Fail with a custom message",
        "syntax": "fail: msg=<text>",
        "example": "- fail:\n    msg: 'Required variable db_password is not defined'\n  when: db_password is not defined",
    },
    "meta": {
        "description": "Execute Ansible meta-tasks (flush handlers, end play, etc.)",
        "syntax": "meta: <action>",
        "example": "- meta: flush_handlers",
    },
    "register": {
        "description": "Store task output in a variable (used with any module)",
        "syntax": "<module>: ...\n  register: <var_name>",
        "example": "- command: whoami\n  register: current_user\n- debug:\n    var: current_user.stdout",
    },
    "handlers": {
        "description": "Tasks triggered by 'notify' (restart services, etc.)",
        "syntax": "handlers:\n  - name: <handler_name>\n    <module>: ...",
        "example": "handlers:\n  - name: restart nginx\n    service:\n      name: nginx\n      state: restarted",
    },
    "block": {
        "description": "Group tasks with error handling (block/rescue/always)",
        "syntax": "block:\n  - <tasks>\n  rescue:\n  - <error_tasks>\n  always:\n  - <cleanup_tasks>",
        "example": "- block:\n    - command: /opt/app/deploy.sh\n  rescue:\n    - command: /opt/app/rollback.sh\n  always:\n    - debug:\n        msg: 'Deploy attempt complete'",
    },
    "loop": {
        "description": "Iterate over a list of items",
        "syntax": "<module>: ...\n  loop: <list>",
        "example": "- apt:\n    name: \"{{ item }}\"\n    state: present\n  loop:\n    - nginx\n    - curl\n    - jq",
    },
    "when": {
        "description": "Conditional execution",
        "syntax": "<module>: ...\n  when: <condition>",
        "example": "- apt:\n    name: nginx\n  when: ansible_os_family == 'Debian'",
    },
}


# ---------------------------------------------------------------------------
# Playbook Templates — Common patterns for quick generation
# ---------------------------------------------------------------------------

PLAYBOOK_TEMPLATES: Dict[str, str] = {
    "basic": """---
- name: Basic playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    app_name: myapp
    app_version: "1.0.0"

  tasks:
    - name: Ensure required packages are installed
      package:
        name: "{{ item }}"
        state: present
      loop:
        - curl
        - wget
        - jq

    - name: Create application directory
      file:
        path: "/opt/{{ app_name }}"
        state: directory
        owner: root
        mode: '0755'

    - name: Display completion message
      debug:
        msg: "Setup complete for {{ app_name }} v{{ app_version }}"
""",
    "service_mgmt": """---
- name: Service management playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    service_name: nginx
    service_config_src: templates/nginx.conf.j2
    service_config_dest: /etc/nginx/nginx.conf

  tasks:
    - name: Install service package
      package:
        name: "{{ service_name }}"
        state: latest

    - name: Deploy configuration
      template:
        src: "{{ service_config_src }}"
        dest: "{{ service_config_dest }}"
        owner: root
        mode: '0644'
        backup: yes
      notify: restart service

    - name: Ensure service is running and enabled
      service:
        name: "{{ service_name }}"
        state: started
        enabled: yes

  handlers:
    - name: restart service
      service:
        name: "{{ service_name }}"
        state: restarted
""",
    "package_install": """---
- name: Package installation playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    packages_common:
      - vim
      - htop
      - tmux
      - git
      - curl
      - jq
      - tree
      - unzip
    packages_debian:
      - apt-transport-https
      - ca-certificates
    packages_redhat:
      - epel-release

  tasks:
    - name: Update package cache (Debian)
      apt:
        update_cache: yes
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

    - name: Install common packages
      package:
        name: "{{ item }}"
        state: present
      loop: "{{ packages_common }}"

    - name: Install Debian-specific packages
      apt:
        name: "{{ item }}"
        state: present
      loop: "{{ packages_debian }}"
      when: ansible_os_family == "Debian"

    - name: Install RedHat-specific packages
      yum:
        name: "{{ item }}"
        state: present
      loop: "{{ packages_redhat }}"
      when: ansible_os_family == "RedHat"
""",
    "user_mgmt": """---
- name: User management playbook
  hosts: all
  become: yes
  gather_facts: no

  vars:
    users:
      - name: deploy
        groups: docker,sudo
        shell: /bin/bash
        ssh_key: "ssh-rsa AAAA..."
      - name: monitor
        groups: ""
        shell: /bin/bash
        ssh_key: ""

  tasks:
    - name: Create user groups
      group:
        name: "{{ item }}"
        state: present
      loop:
        - docker
        - appgroup

    - name: Create users
      user:
        name: "{{ item.name }}"
        groups: "{{ item.groups }}"
        shell: "{{ item.shell }}"
        create_home: yes
        state: present
      loop: "{{ users }}"

    - name: Set authorized keys
      authorized_key:
        user: "{{ item.name }}"
        key: "{{ item.ssh_key }}"
        state: present
      loop: "{{ users }}"
      when: item.ssh_key | length > 0
""",
    "docker": """---
- name: Docker deployment playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    docker_compose_version: "2.24.0"
    app_image: "myapp:latest"
    app_name: myapp
    app_port: 8080

  tasks:
    - name: Install Docker prerequisites
      apt:
        name:
          - apt-transport-https
          - ca-certificates
          - curl
          - gnupg
          - lsb-release
        state: present
        update_cache: yes
      when: ansible_os_family == "Debian"

    - name: Pull application image
      docker_image:
        name: "{{ app_image }}"
        source: pull
        force_source: yes

    - name: Stop existing container
      docker_container:
        name: "{{ app_name }}"
        state: absent
      ignore_errors: yes

    - name: Start application container
      docker_container:
        name: "{{ app_name }}"
        image: "{{ app_image }}"
        state: started
        restart_policy: unless-stopped
        ports:
          - "{{ app_port }}:80"
        env:
          NODE_ENV: production

    - name: Wait for application to be healthy
      uri:
        url: "http://localhost:{{ app_port }}/health"
        status_code: 200
      retries: 10
      delay: 5
      register: health
      until: health.status == 200
""",
    "rolling_update": """---
- name: Rolling update playbook
  hosts: webservers
  become: yes
  serial: "25%"
  max_fail_percentage: 25

  vars:
    app_version: "{{ deploy_version | default('latest') }}"
    health_url: "http://localhost:8080/health"

  pre_tasks:
    - name: Remove from load balancer
      uri:
        url: "http://{{ lb_host }}/api/servers/{{ inventory_hostname }}/drain"
        method: POST
      delegate_to: localhost
      ignore_errors: yes

    - name: Wait for connections to drain
      pause:
        seconds: 30

  tasks:
    - name: Stop application
      service:
        name: myapp
        state: stopped

    - name: Deploy new version
      copy:
        src: "releases/myapp-{{ app_version }}.tar.gz"
        dest: /opt/myapp/
      notify: restart application

    - name: Verify health
      uri:
        url: "{{ health_url }}"
        status_code: 200
      retries: 12
      delay: 5
      register: health
      until: health.status == 200

  post_tasks:
    - name: Re-add to load balancer
      uri:
        url: "http://{{ lb_host }}/api/servers/{{ inventory_hostname }}/enable"
        method: POST
      delegate_to: localhost

  handlers:
    - name: restart application
      service:
        name: myapp
        state: restarted
""",
    "firewall": """---
- name: Firewall configuration playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    allowed_tcp_ports:
      - 22    # SSH
      - 80    # HTTP
      - 443   # HTTPS
      - 8080  # Application
    allowed_networks:
      - "10.0.0.0/8"
      - "172.16.0.0/12"

  tasks:
    - name: Configure UFW (Debian)
      block:
        - name: Set default deny incoming
          ufw:
            direction: incoming
            policy: deny

        - name: Allow TCP ports
          ufw:
            rule: allow
            port: "{{ item }}"
            proto: tcp
          loop: "{{ allowed_tcp_ports }}"

        - name: Allow internal networks
          ufw:
            rule: allow
            src: "{{ item }}"
          loop: "{{ allowed_networks }}"

        - name: Enable UFW
          ufw:
            state: enabled
      when: ansible_os_family == "Debian"

    - name: Configure firewalld (RedHat)
      block:
        - name: Allow TCP ports
          firewalld:
            port: "{{ item }}/tcp"
            permanent: yes
            state: enabled
            immediate: yes
          loop: "{{ allowed_tcp_ports }}"

        - name: Allow internal networks
          firewalld:
            source: "{{ item }}"
            zone: trusted
            permanent: yes
            state: enabled
            immediate: yes
          loop: "{{ allowed_networks }}"
      when: ansible_os_family == "RedHat"
""",
    "monitoring": """---
- name: Monitoring setup playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    node_exporter_version: "1.7.0"
    prometheus_port: 9100

  tasks:
    - name: Create monitoring user
      user:
        name: monitoring
        system: yes
        shell: /usr/sbin/nologin
        create_home: no

    - name: Download node_exporter
      get_url:
        url: "https://github.com/prometheus/node_exporter/releases/download/v{{ node_exporter_version }}/node_exporter-{{ node_exporter_version }}.linux-amd64.tar.gz"
        dest: /tmp/node_exporter.tar.gz

    - name: Extract node_exporter
      unarchive:
        src: /tmp/node_exporter.tar.gz
        dest: /usr/local/bin/
        remote_src: yes
        extra_opts: ['--strip-components=1', '--wildcards', '*/node_exporter']

    - name: Create systemd unit
      copy:
        content: |
          [Unit]
          Description=Node Exporter
          After=network.target
          [Service]
          User=monitoring
          ExecStart=/usr/local/bin/node_exporter
          [Install]
          WantedBy=multi-user.target
        dest: /etc/systemd/system/node_exporter.service

    - name: Start node_exporter
      systemd:
        name: node_exporter
        state: started
        enabled: yes
        daemon_reload: yes
""",
    "backup": """---
- name: Backup playbook
  hosts: all
  become: yes
  gather_facts: yes

  vars:
    backup_dirs:
      - /etc
      - /opt/app/data
      - /var/lib/postgresql
    backup_dest: /backups
    backup_retain_days: 30
    backup_timestamp: "{{ ansible_date_time.date }}"

  tasks:
    - name: Create backup directory
      file:
        path: "{{ backup_dest }}/{{ backup_timestamp }}"
        state: directory
        mode: '0700'

    - name: Backup directories
      archive:
        path: "{{ item }}"
        dest: "{{ backup_dest }}/{{ backup_timestamp }}/{{ item | basename }}.tar.gz"
        format: gz
      loop: "{{ backup_dirs }}"
      ignore_errors: yes

    - name: Cleanup old backups
      find:
        paths: "{{ backup_dest }}"
        file_type: directory
        age: "{{ backup_retain_days }}d"
      register: old_backups

    - name: Remove old backups
      file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"
      when: old_backups.files | length > 0
""",
    "deployment": """---
- name: Application deployment playbook
  hosts: app_servers
  become: yes
  gather_facts: yes

  vars:
    app_name: myapp
    app_user: appuser
    app_dir: "/opt/{{ app_name }}"
    app_version: "{{ deploy_version }}"
    app_repo: "https://github.com/org/{{ app_name }}.git"
    venv_dir: "{{ app_dir }}/venv"

  tasks:
    - name: Create application user
      user:
        name: "{{ app_user }}"
        system: yes
        home: "{{ app_dir }}"
        shell: /bin/bash

    - name: Clone/update application
      git:
        repo: "{{ app_repo }}"
        dest: "{{ app_dir }}/src"
        version: "{{ app_version }}"
        force: yes
      become_user: "{{ app_user }}"

    - name: Create virtual environment
      pip:
        requirements: "{{ app_dir }}/src/requirements.txt"
        virtualenv: "{{ venv_dir }}"
        virtualenv_command: python3 -m venv

    - name: Run database migrations
      command: "{{ venv_dir }}/bin/python manage.py migrate"
      args:
        chdir: "{{ app_dir }}/src"
      become_user: "{{ app_user }}"

    - name: Deploy systemd service
      template:
        src: templates/app.service.j2
        dest: "/etc/systemd/system/{{ app_name }}.service"
      notify: restart app

    - name: Ensure app is running
      systemd:
        name: "{{ app_name }}"
        state: started
        enabled: yes
        daemon_reload: yes

  handlers:
    - name: restart app
      systemd:
        name: "{{ app_name }}"
        state: restarted
""",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_yaml_safe(content: str) -> Tuple[Optional[Any], Optional[str]]:
    """Parse YAML content safely, return (parsed, error)."""
    if _YAML_AVAILABLE:
        try:
            parsed = _yaml.safe_load(content)
            return parsed, None
        except _yaml.YAMLError as e:
            return None, str(e)
    # Regex fallback — basic structure detection
    if not content.strip().startswith('---') and not content.strip().startswith('-'):
        return None, "Content does not look like YAML (no --- or - at start)"
    return {"_fallback": True}, None


def _extract_yaml_from_input(user_input: str, **kwargs: Any) -> str:
    """Extract YAML content from user input or kwargs."""
    if "playbook_content" in kwargs and kwargs["playbook_content"]:
        return kwargs["playbook_content"]
    if "yaml_content" in kwargs and kwargs["yaml_content"]:
        return kwargs["yaml_content"]
    # Try to extract YAML block from user input
    yaml_match = re.search(r'```(?:yaml|yml)?\s*\n(.*?)```', user_input, re.DOTALL)
    if yaml_match:
        return yaml_match.group(1)
    # If input starts with --- or - name:, treat entire input as YAML
    stripped = user_input.strip()
    if stripped.startswith('---') or stripped.startswith('- name:'):
        return stripped
    return ""


# ---------------------------------------------------------------------------
# Handler: Validate Playbook
# ---------------------------------------------------------------------------

def ansible_validate_playbook(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Validate Ansible playbook YAML structure and best practices."""
    yaml_content = _extract_yaml_from_input(user_input, **kwargs)
    if not yaml_content:
        return {
            "success": False,
            "output": "No playbook YAML found. Provide YAML content in a ```yaml code block or pass playbook_content parameter.",
        }

    parsed, parse_error = _parse_yaml_safe(yaml_content)
    if parse_error:
        return {
            "success": False,
            "output": f"YAML Parse Error: {parse_error}",
            "errors": [f"YAML syntax error: {parse_error}"],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []

    # Structural validation
    if not isinstance(parsed, list):
        errors.append("Playbook must be a list of plays (starts with '- name: ...')")
        return {"success": False, "output": "\n".join(errors), "errors": errors, "warnings": []}

    play_count = 0
    total_tasks = 0
    has_handlers = False

    for i, play in enumerate(parsed):
        if not isinstance(play, dict):
            errors.append(f"Play {i+1}: Must be a dictionary")
            continue

        play_count += 1

        # Required fields
        if "hosts" not in play and "name" not in play:
            warnings.append(f"Play {i+1}: Missing both 'name' and 'hosts'")
        if "hosts" not in play:
            errors.append(f"Play {i+1}: Missing required 'hosts' key")

        # Task validation
        tasks = play.get("tasks", [])
        if isinstance(tasks, list):
            total_tasks += len(tasks)
            for j, task in enumerate(tasks):
                if isinstance(task, dict):
                    if "name" not in task:
                        warnings.append(f"Play {i+1}, Task {j+1}: Missing 'name' (best practice)")

        # Handler validation
        handlers = play.get("handlers", [])
        if handlers:
            has_handlers = True
            if isinstance(handlers, list):
                for h in handlers:
                    if isinstance(h, dict) and "name" not in h:
                        errors.append(f"Play {i+1}: Handler missing 'name' key")

    # Best practices
    yaml_str = yaml_content

    # Check for hardcoded passwords
    if re.search(r'password:\s*["\']?[^{]', yaml_str):
        warnings.append("Hardcoded password detected — use ansible-vault or vars_prompt")

    # Check for no_log on sensitive tasks
    if re.search(r'password|secret|token|api_key', yaml_str, re.I):
        if 'no_log:' not in yaml_str:
            warnings.append("Sensitive data detected but no 'no_log: true' on tasks")

    # Check for become
    if 'become:' not in yaml_str and total_tasks > 0:
        warnings.append("No 'become: yes' found — verify if privilege escalation is needed")

    # Check for changed_when on command/shell tasks
    cmd_tasks = len(re.findall(r'\b(command|shell|raw):', yaml_str))
    changed_when_count = len(re.findall(r'changed_when:', yaml_str))
    if cmd_tasks > 0 and changed_when_count == 0:
        warnings.append(f"{cmd_tasks} command/shell tasks without 'changed_when:' — may report false changes")

    # Check for notify without handlers
    notify_count = len(re.findall(r'notify:', yaml_str))
    if notify_count > 0 and not has_handlers:
        errors.append(f"{notify_count} 'notify:' directives but no handlers section defined")

    # Check for tags
    if total_tasks > 5 and 'tags:' not in yaml_str:
        warnings.append("Large playbook without tags — consider adding tags for selective execution")

    # Check for vars usage consistency
    var_refs = re.findall(r'\{\{\s*(\w+)', yaml_str)
    var_defs = re.findall(r'^\s+(\w+):', yaml_str, re.MULTILINE)
    undefined_vars = set(v for v in var_refs if v not in var_defs
                        and v not in ('item', 'ansible_os_family', 'ansible_hostname',
                                      'ansible_date_time', 'inventory_hostname', 'ansible_distribution',
                                      'ansible_env', 'hostvars', 'groups', 'group_names'))
    # Don't report as errors since vars might come from inventory/group_vars
    if undefined_vars:
        warnings.append(f"Variables used but not defined in playbook: {', '.join(sorted(undefined_vars)[:5])} — ensure they're in inventory/group_vars")

    valid = len(errors) == 0
    output_lines = []
    if valid:
        output_lines.append(f"Playbook is valid: {play_count} play(s), {total_tasks} task(s)")
    else:
        output_lines.append(f"Playbook has {len(errors)} error(s)")

    if errors:
        output_lines.append("\nErrors:")
        for e in errors:
            output_lines.append(f"  - {e}")
    if warnings:
        output_lines.append("\nWarnings / Best Practice Suggestions:")
        for w in warnings:
            output_lines.append(f"  - {w}")

    return {
        "success": valid,
        "output": "\n".join(output_lines),
        "errors": errors,
        "warnings": warnings,
        "structure": {
            "plays": play_count,
            "tasks": total_tasks,
            "has_handlers": has_handlers,
        },
    }


# ---------------------------------------------------------------------------
# Handler: Generate Playbook
# ---------------------------------------------------------------------------

def _get_llm():
    """Get the LLM instance for playbook generation."""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))
        from llm_utils import LLM
        return LLM
    except Exception:
        return None


def _find_best_template(description: str) -> Optional[str]:
    """Find the best matching template based on keywords."""
    lower_desc = description.lower()
    keyword_map = {
        "service": "service_mgmt", "nginx": "service_mgmt",
        "apache": "service_mgmt", "systemd": "service_mgmt",
        "install": "package_install", "package": "package_install",
        "apt": "package_install", "yum": "package_install",
        "user": "user_mgmt", "account": "user_mgmt", "ssh key": "user_mgmt",
        "docker": "docker", "container": "docker",
        "rolling": "rolling_update", "zero downtime": "rolling_update",
        "blue green": "rolling_update",
        "firewall": "firewall", "ufw": "firewall", "iptables": "firewall",
        "monitor": "monitoring", "prometheus": "monitoring",
        "node_exporter": "monitoring",
        "backup": "backup", "archive": "backup",
        "deploy": "deployment", "release": "deployment", "git clone": "deployment",
    }
    for keyword, tpl_name in keyword_map.items():
        if keyword in lower_desc:
            return tpl_name
    return None


def ansible_generate_playbook(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Generate an Ansible playbook from natural language description using LLM."""
    template_name = kwargs.get("template", "")
    description = kwargs.get("description", user_input)

    # Direct template match (explicit template= param)
    if template_name and template_name != "custom" and template_name in PLAYBOOK_TEMPLATES:
        return {
            "success": True,
            "output": PLAYBOOK_TEMPLATES[template_name],
            "template_used": template_name,
        }

    # Find a reference template to use as context for the LLM
    ref_template_name = _find_best_template(description)
    ref_template = PLAYBOOK_TEMPLATES.get(ref_template_name or "basic", "")

    # Try LLM-based generation
    llm = _get_llm()
    if llm is not None:
        try:
            prompt = f"""You are an expert Ansible automation engineer. Generate a complete, production-ready Ansible playbook based on the user's request.

Requirements:
- Output ONLY valid YAML (the playbook) — no markdown fences, no explanation
- Start with ---
- Use real Ansible modules (apt, yum, shell, command, copy, template, service, file, user, etc.)
- Include proper task names, become/privilege escalation where needed
- Add variables in vars section for anything that should be customizable
- Use handlers for service restarts when appropriate
- Include comments with # <-- Change: markers for values the user should customize

Reference template for style (adapt to the user's actual request):
```yaml
{ref_template[:1500]}
```

User request: {description}

Generate the complete playbook now:"""
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            # Strip markdown fences if LLM wraps output
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                # Remove first line (```yaml) and last line (```)
                if lines[-1].strip() == "```":
                    lines = lines[1:-1]
                else:
                    lines = lines[1:]
                content = "\n".join(lines)
            if not content.startswith("---"):
                content = "---\n" + content
            return {
                "success": True,
                "output": content,
                "template_used": f"llm_generated (ref: {ref_template_name or 'none'})",
                "note": "Generated by LLM based on your description. Review and customize before use.",
            }
        except Exception as exc:
            logger.warning("LLM generation failed, falling back to template: %s", exc)

    # Fallback: return best matching template with customization note
    if ref_template_name:
        return {
            "success": True,
            "output": PLAYBOOK_TEMPLATES[ref_template_name],
            "template_used": ref_template_name,
            "note": f"LLM unavailable. Returned '{ref_template_name}' template — customize for your needs.",
        }

    # Last resort: basic template
    return {
        "success": True,
        "output": PLAYBOOK_TEMPLATES.get("basic", "---\n- name: Playbook\n  hosts: all\n  tasks: []"),
        "template_used": "basic",
        "note": "LLM unavailable. Returned basic template — add your tasks.",
    }


# ---------------------------------------------------------------------------
# Handler: Explain Playbook
# ---------------------------------------------------------------------------

def ansible_explain_playbook(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Explain an Ansible playbook section by section."""
    yaml_content = _extract_yaml_from_input(user_input, **kwargs)
    if not yaml_content:
        return {"success": False, "output": "No playbook YAML found to explain."}

    parsed, parse_error = _parse_yaml_safe(yaml_content)
    if parse_error:
        return {"success": False, "output": f"Cannot parse YAML: {parse_error}"}

    explanations: List[str] = []
    explanations.append("## Playbook Explanation\n")

    if not isinstance(parsed, list):
        explanations.append("This YAML is not a standard playbook (expected a list of plays).")
        return {"success": True, "output": "\n".join(explanations)}

    for i, play in enumerate(parsed):
        if not isinstance(play, dict):
            continue

        play_name = play.get("name", f"Unnamed Play {i+1}")
        hosts = play.get("hosts", "unspecified")
        become = play.get("become", False)
        gather = play.get("gather_facts", True)
        serial = play.get("serial", None)

        explanations.append(f"### Play {i+1}: {play_name}")
        explanations.append(f"- **Target hosts:** `{hosts}`")
        explanations.append(f"- **Privilege escalation:** {'Yes (sudo/become)' if become else 'No'}")
        explanations.append(f"- **Gather facts:** {'Yes' if gather else 'No'}")
        if serial:
            explanations.append(f"- **Serial execution:** {serial} (rolling update pattern)")

        # Variables
        if "vars" in play:
            var_names = list(play["vars"].keys()) if isinstance(play["vars"], dict) else []
            if var_names:
                explanations.append(f"- **Variables defined:** {', '.join(var_names[:10])}")

        # Tasks
        tasks = play.get("tasks", [])
        if tasks and isinstance(tasks, list):
            explanations.append(f"\n**Tasks ({len(tasks)}):**")
            for j, task in enumerate(tasks):
                if not isinstance(task, dict):
                    continue
                task_name = task.get("name", f"Task {j+1}")
                # Find the module used
                module = "unknown"
                for key in task:
                    if key not in ("name", "register", "when", "loop", "with_items",
                                   "notify", "tags", "become", "become_user",
                                   "changed_when", "failed_when", "ignore_errors",
                                   "no_log", "delegate_to", "retries", "delay",
                                   "until", "vars", "environment", "args", "block",
                                   "rescue", "always"):
                        module = key
                        break
                explanation = f"{j+1}. **{task_name}** — uses `{module}` module"
                if "when" in task:
                    explanation += f" (conditional: `{task['when']}`)"
                if "loop" in task or "with_items" in task:
                    explanation += " (iterates over list)"
                if "notify" in task:
                    explanation += f" → triggers handler: `{task['notify']}`"
                if "register" in task:
                    explanation += f" → saves result to `{task['register']}`"
                explanations.append(explanation)

        # Handlers
        handlers = play.get("handlers", [])
        if handlers and isinstance(handlers, list):
            handler_names = [h.get("name", "unnamed") for h in handlers if isinstance(h, dict)]
            explanations.append(f"\n**Handlers:** {', '.join(handler_names)}")
            explanations.append("(Handlers run only when notified by a task that made changes)")

        # Pre/post tasks
        for section in ("pre_tasks", "post_tasks"):
            items = play.get(section, [])
            if items and isinstance(items, list):
                explanations.append(f"\n**{section.replace('_', ' ').title()}:** {len(items)} task(s)")

        explanations.append("")

    return {"success": True, "output": "\n".join(explanations)}


# ---------------------------------------------------------------------------
# Handler: Improve Playbook
# ---------------------------------------------------------------------------

def ansible_improve_playbook(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Suggest improvements for an Ansible playbook."""
    yaml_content = _extract_yaml_from_input(user_input, **kwargs)
    if not yaml_content:
        return {"success": False, "output": "No playbook YAML found to improve."}

    parsed, parse_error = _parse_yaml_safe(yaml_content)
    if parse_error:
        return {"success": False, "output": f"Cannot parse YAML: {parse_error}"}

    suggestions: List[Dict[str, str]] = []
    yaml_str = yaml_content

    # --- Structure suggestions ---

    # Large playbook → suggest roles
    if isinstance(parsed, list):
        total_tasks = sum(len(p.get("tasks", [])) for p in parsed if isinstance(p, dict))
        if total_tasks > 20:
            suggestions.append({
                "category": "Structure",
                "severity": "medium",
                "suggestion": f"Playbook has {total_tasks} tasks. Consider refactoring into Ansible roles for maintainability.",
                "example": "# Create roles:\n#   roles/common/tasks/main.yml\n#   roles/app/tasks/main.yml\n# Then: roles:\n#   - common\n#   - app",
            })

    # --- Idempotency ---
    cmd_count = len(re.findall(r'\b(command|shell|raw):', yaml_str))
    changed_when_count = len(re.findall(r'changed_when:', yaml_str))
    if cmd_count > 0 and changed_when_count < cmd_count:
        suggestions.append({
            "category": "Idempotency",
            "severity": "high",
            "suggestion": f"{cmd_count} command/shell tasks found but only {changed_when_count} have 'changed_when:'. Add 'changed_when: false' for read-only commands or proper change detection.",
            "example": "- command: whoami\n  register: result\n  changed_when: false",
        })

    # --- Error handling ---
    if 'block:' not in yaml_str and total_tasks > 5 if isinstance(parsed, list) else True:
        suggestions.append({
            "category": "Error Handling",
            "severity": "medium",
            "suggestion": "No block/rescue/always structure found. Use blocks for error handling on critical operations.",
            "example": "- block:\n    - name: Deploy\n      command: deploy.sh\n  rescue:\n    - name: Rollback\n      command: rollback.sh\n  always:\n    - name: Cleanup\n      file: path=/tmp/deploy state=absent",
        })

    # --- Security ---
    if re.search(r'password:\s*["\']?[^{]', yaml_str):
        suggestions.append({
            "category": "Security",
            "severity": "critical",
            "suggestion": "Hardcoded password detected. Use ansible-vault to encrypt sensitive values.",
            "example": "# Encrypt: ansible-vault encrypt_string 'mysecret' --name 'db_password'\n# Use: password: \"{{ db_password }}\"",
        })

    if re.search(r'(password|secret|token|api_key)', yaml_str, re.I) and 'no_log:' not in yaml_str:
        suggestions.append({
            "category": "Security",
            "severity": "high",
            "suggestion": "Sensitive data handling without 'no_log: true'. Add to prevent secrets appearing in logs.",
            "example": "- name: Set database password\n  command: set_password.sh\n  no_log: true",
        })

    # --- Performance ---
    if 'serial:' not in yaml_str and isinstance(parsed, list):
        for play in parsed:
            if isinstance(play, dict) and play.get("hosts") not in ("localhost", "127.0.0.1"):
                suggestions.append({
                    "category": "Performance",
                    "severity": "low",
                    "suggestion": "Consider 'serial:' for controlled rollout across multiple hosts.",
                    "example": "- hosts: webservers\n  serial: \"25%\"  # Deploy to 25% at a time",
                })
                break

    if re.search(r'with_items:', yaml_str):
        suggestions.append({
            "category": "Modernization",
            "severity": "low",
            "suggestion": "'with_items:' is deprecated. Use 'loop:' instead.",
            "example": "# Old:\n#   with_items: \"{{ packages }}\"\n# New:\n  loop: \"{{ packages }}\"",
        })

    # --- Tags ---
    if 'tags:' not in yaml_str and total_tasks > 3 if isinstance(parsed, list) else True:
        suggestions.append({
            "category": "Usability",
            "severity": "low",
            "suggestion": "Add tags for selective task execution (e.g., --tags deploy, --skip-tags test).",
            "example": "- name: Install packages\n  apt: ...\n  tags:\n    - setup\n    - packages",
        })

    # --- Handlers ---
    service_tasks = len(re.findall(r'\b(template|copy|lineinfile|blockinfile):', yaml_str))
    notify_count = len(re.findall(r'notify:', yaml_str))
    if service_tasks > 0 and notify_count == 0:
        suggestions.append({
            "category": "Best Practice",
            "severity": "medium",
            "suggestion": f"{service_tasks} configuration change tasks without 'notify:'. Use handlers to restart services only when config changes.",
            "example": "- template:\n    src: app.conf.j2\n    dest: /etc/app/app.conf\n  notify: restart app\n\nhandlers:\n  - name: restart app\n    service: name=app state=restarted",
        })

    # Format output
    if not suggestions:
        return {
            "success": True,
            "output": "Playbook looks good! No major improvements needed.",
            "suggestions": [],
        }

    output_lines = [f"## Improvement Suggestions ({len(suggestions)} found)\n"]
    for s in suggestions:
        severity_icon = {"critical": "[CRITICAL]", "high": "[HIGH]", "medium": "[MEDIUM]", "low": "[LOW]"}.get(s["severity"], "")
        output_lines.append(f"### {severity_icon} {s['category']}")
        output_lines.append(s["suggestion"])
        output_lines.append(f"```yaml\n{s['example']}\n```\n")

    return {
        "success": True,
        "output": "\n".join(output_lines),
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Handler: Module Reference
# ---------------------------------------------------------------------------

def ansible_module_reference(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Look up Ansible module reference information."""
    query = kwargs.get("module", user_input).lower().strip()

    # Direct module lookup
    if query in ANSIBLE_MODULES:
        mod = ANSIBLE_MODULES[query]
        output = f"## ansible.builtin.{query}\n\n"
        output += f"**Description:** {mod['description']}\n\n"
        output += f"**Syntax:**\n```yaml\n{mod['syntax']}\n```\n\n"
        output += f"**Example:**\n```yaml\n{mod['example']}\n```"
        return {"success": True, "output": output, "module": query}

    # Fuzzy search
    matches = []
    for mod_name, mod_info in ANSIBLE_MODULES.items():
        if query in mod_name or query in mod_info["description"].lower():
            matches.append((mod_name, mod_info["description"]))

    if matches:
        output = f"## Modules matching '{query}':\n\n"
        for name, desc in matches[:10]:
            output += f"- **{name}**: {desc}\n"
        output += "\nUse a specific module name for detailed reference."
        return {"success": True, "output": output, "matches": [m[0] for m in matches]}

    # List all modules
    if query in ("list", "all", "help", ""):
        categories = {
            "File Management": ["copy", "template", "file", "lineinfile", "blockinfile", "replace", "stat", "find", "archive", "unarchive", "fetch", "synchronize"],
            "Package Management": ["apt", "yum", "dnf", "pip", "package"],
            "Service Management": ["service", "systemd"],
            "User/Group": ["user", "group", "authorized_key"],
            "System": ["command", "shell", "raw", "script", "cron", "hostname", "timezone", "sysctl", "mount"],
            "Network/Security": ["uri", "get_url", "firewalld", "ufw", "known_hosts", "wait_for"],
            "Database": ["mysql_db", "postgresql_db", "postgresql_user"],
            "Container": ["docker_container", "docker_image"],
            "Version Control": ["git"],
            "Flow Control": ["debug", "assert", "fail", "pause", "meta", "set_fact", "include_tasks", "include_role", "import_tasks", "import_role"],
            "Patterns": ["register", "handlers", "block", "loop", "when"],
        }
        output = "## Ansible Module Quick Reference\n\n"
        for cat, mods in categories.items():
            output += f"### {cat}\n"
            for m in mods:
                info = ANSIBLE_MODULES.get(m, {})
                desc = info.get("description", "")
                output += f"- **{m}**: {desc}\n"
            output += "\n"
        return {"success": True, "output": output}

    return {
        "success": False,
        "output": f"Module '{query}' not found. Use 'list' to see all available modules.",
    }
