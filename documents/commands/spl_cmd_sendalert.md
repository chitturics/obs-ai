---
 command: sendalert
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Sendalert
 title: sendalert
 download_date: 2026-02-03 09:16:39
---

 # sendalert

Use the sendalert command to invoke a custom alert action. The command gathers the configuration for the alert action from the alert_actions.conf file and the saved search and custom parameters passed using the command arguments. Then the command performs token replacement. The command determines the alert action script and arguments to run, creates the alert action payload and executes the script, handing over the payload by using STDIN to the script process.

When running the custom script, the sendalert command honors the maxtime setting from the alert_actions.conf file and terminates the process if the process runs longer than the configured threshold. By default the threshold is set to 5 minutes.

See Write the script for a custom alert action for Splunk Cloud Platform or Splunk Enterprise in the Developer Guide on the Developer Portal.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

sendalert <alert_action_name> [results_link=<url>] [results_path=<path>] [param.<name>=<"value">...]

#### Required arguments

#### Optional arguments

When you use the sendalert command in an ad hoc search, the command might be called multiple times if there are a large number of search results. This occurs because previewing the search results on the Statistics tab is enabled by default.  If you are using an ad hoc search to test the sendalert command,  testing turn off preview to avoid the command being called multiple times.

When the sendalert command is included in a saved search, such as a scheduled report or a scheduled search, the command is called only one time.

#### Capability required

To use this command, you must have a role with the run_sendalert capability. See Define roles on the Splunk platform with capabilities.

#### Search results format

When the sendalert command is used in a search or in an alert action, the search results are stored in an archive file in the dispatch directory using the CSV format. The file name is results.csv.gz. The default format for the search results is SRS, a Splunk-specific binary format for the search results. The CSV format for the archive file is used so that scripts can process the results file. The default SRS format is not designed to be parsed by scripts.

The archived search results format is controlled through the forceCsvResults setting. This setting is in the  [default] stanza in the alert_actions.conf file.

Example 1: Invoke an alert action without any arguments. The alert action script handles checking whether there are necessary parameters that are missing and report the error appropriately.

Example 2: Trigger the hipchat custom alert action and pass in room and message as custom parameters.

Example 3: Trigger the servicenow alert option.
 