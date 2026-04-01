---
 command: runshellscript
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Runshellscript
 title: runshellscript
 download_date: 2026-02-03 09:15:59
---

 # runshellscript

CAUTION: The runshellscript command is an internal, unsupported, experimental command. See 
About internal commands.

For Splunk Enterprise deployments, executes scripted alerts. This command is not supported as a search command.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

runshellscript <script-filename> <result-count> <search-terms> <search-string> <savedsearch-name> <description> <results-url> <deprecated-arg> <results_file> <search-ID> <results-file-path-deprecated-arg>

The script file needs to be located in either $SPLUNK_HOME/etc/system/bin/scripts OR $SPLUNK_HOME/etc/apps/<app-name>/bin/scripts. The following table describes the arguments passed to the script.

| Argument | Description |
| --- | --- |
| $0 | The filename of the script. |
| $1 | The result count, or number of events returned. |
| $2 | The search terms. |
| $3 | The fully qualified search string. |
| $4 | The name of the saved search. |
| $5 | The description or trigger reason. For example, "The number of events was greater than 1." |
| $6 | The link to saved search results. |
| $7 | DEPRECATED - empty string argument. |
| $8 | The search ID. |

The runshellscript command validates the $8 search ID argument on

- Whether the provided search ID exists.
- Whether you have permission to access the provided search ID.
 