---
 command: rest
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/rest
 title: rest
 download_date: 2026-02-03 09:15:26
---

 # rest

The rest command reads a Splunk REST API endpoint and returns the resource data as a search result.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The rest command authenticates using the ID of the person that runs the command.

#### Strict error handling

Use the strict argument to make rest searches fail whenever they encounter an error condition. You can set this at the system level for all rest searches by changing restprocessor_errors_fatal in limits.conf.

Note: If you use Splunk Cloud Platform, file a Support ticket to change the restprocessor_errors_fatal setting.

Use the strict argument to override the restprocessor_errors_fatal setting for a rest search.

#### 1. Access saved search jobs

#### 2.  Find all saved searches with searches that include a specific sourcetype

Find all saved searches with search strings that include the speccsv sourcetype.

#### 3. Showing events only associated with the current user

To create reports that only show events associated with the logged in user, you can add the current search user to all events.

#### 4. Use the GET method pagination and filtering arguments

Most GET methods support a set of pagination and filtering arguments.

To determine if an endpoint supports these arguments, find the endpoint in the Splunk platform  REST API Reference Manual. Click Expand on the GET method and look for a link to the Pagination and filtering arguments topic. For more information about the Pagination and filtering arguments, see the Request and response details in the Splunk Cloud Platform REST API Reference manual.

The following example uses the search argument for the saved/searches endpoint to identify if a search is scheduled and deactivated. The search looks for scheduled searches on Splunk servers that match the Monitoring Console role of "search heads".

Here is an explanation for each part of this search:

| Description | Part of the search |
| --- | --- |
| The name of the REST call. | |rest /servicesNS/-/-/saved/searches |
| Look only at Splunk servers that match the Monitoring Console role of "search heads". | splunk_server_group=dmc_group_search_head |
| Don't time out waiting for the REST call to finish. | timeout=0 |
| Look only for scheduled searches. | search="is_scheduled=1" |
| Look only for active searches (not deactivated). | search="disabled=0" |

#### 5. Return a table of results with custom endpoints

When you create a custom endpoint, you can format the response to return a table of results. The following example shows a custom endpoint:

Here's an example of the response you can use to return a table of results:
 