---
 command: xmlunescape
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Xmlunescape
 title: xmlunescape
 download_date: 2026-02-03 09:21:23
---

 # xmlunescape

# xmlunescape

## Description

Un-escapes xml characters, including entity references such as &, <, and >, so that they return to their corresponding characters. For example, &amp; becomes &.

The xmlunescape command is a streaming command. It is distributable streaming by default, but centralized streaming if the local setting specified for the command in the commands.conf file is set to true. See Command types.

## Syntax

xmlunescape maxinputs=<int>

### Optional arguments

Syntax: maxinputs=<int>

Description: The maximum number of inputs per invocation of the command. The xmlunescape command is invoked repeatedly in increments according to the maxinputs argument until the search is complete and all of the results have been displayed. Do not change the value of  maxinputs unless you know what you are doing.

Default: 50000

## Examples

Example 1: Un-escape all XML characters.
 