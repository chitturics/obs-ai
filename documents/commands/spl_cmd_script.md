---
 command: script
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/script
 title: script
 download_date: 2026-02-03 09:16:07
---

 # script

Calls an external python program that can modify or generate search results.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

script <script-name> [<script-arg>...] [maxinputs=<int>]

#### Required arguments

#### Optional arguments

The script command is effectively an alternative way to invoke custom search commands.
See Create custom search commands for apps in Splunk Cloud Platform or Splunk Enterprise in the Developer Guide on the Developer Portal.

The following search:

is the same as this search:

Note: Some functions of the script command have been removed over time. The explicit choice of Perl or Python as an argument is no longer functional and such an argument is ignored. If you need to write Perl search commands, you must declare them as Perl in the commands.conf file. This is not recommended, as you need to determine a number of underdocumented things about the input and output formats. Additionally, support for the etc/searchscripts directory has been removed. Search commands must be located in the bin directory of an app in your Splunk deployment. For more information about creating custom search commands for apps in Splunk Cloud Platform or Splunk Enterprise, see the Developer Guide for Splunk Cloud Platform and Splunk Enterprise.

#### Example 1:

Run the Python script "myscript" with arguments, myarg1 and myarg2; then, email the results.
 