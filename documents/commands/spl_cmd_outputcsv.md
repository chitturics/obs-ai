---
 command: outputcsv
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/outputcsv
 title: outputcsv
 download_date: 2026-02-03 09:13:11
---

 # outputcsv

If you have Splunk Enterprise, this command saves search results to the specified CSV file on the local search head in the $SPLUNK_HOME/var/run/splunk/csv directory. Updates to $SPLUNK_HOME/var/run/*.csv  using the outputcsv command are not replicated across the cluster.

If you have Splunk Cloud Platform, you cannot use this command. Instead, you have these options:

- Export search results using Splunk Web. See Export data using Splunk Web in the Search Manual.
- Export search results using REST API. See Export data using the REST APIs in the Search Manual.
- Create an alert action that includes a CSV file as an email attachment. See  Email notification action in the Alerting Manual.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

outputcsv [append=<bool>] [create_empty=<bool>] [override_if_empty=<bool>] [dispatch=<bool>] [usexml=<bool>] [singlefile=<bool>] [<filename>]

#### Optional arguments

There is no limit to the number of results that can be saved to the CSV file.

#### Internal fields and the outputcsv command

When the outputcsv command is used there are internal fields that are automatically added to the CSV file. The internal fields that are added to the output in the CSV file are:

- _raw
- _time
- _indextime
- _serial
- _sourcetype
- _subsecond

```
fields
```

#### Multivalued fields

The outputcsv command merges values in a multivalued field into single space-delimited value.

#### Distributed deployments

The outputcsv command is not compatible with search head pooling and  search head clustering.

The command saves the *.csv file on the local search head in the $SPLUNK_HOME/var/run/splunk/ directory. The *.csv files are not replicated on the other search heads.

#### 1. Output search results to a CSV file

Output the search results to the mysearch.csv file. The CSV file extension is automatically added to the file name if you don't specify the extension in the search.

#### 2. Add a dynamic timestamp  to the file name

You can add a timestamp to the file name by using a subsearch.

#### 3. Exclude internal fields from the output CSV file

You can exclude unwanted internal fields from the output CSV file. In this example, the fields to exclude are _indextime, _sourcetype, _subsecond, and _serial.

#### 4. Do not delete the CSV file if no search results are returned

Output the search results to the mysearch.csv file if results are returned from the search. Do not delete the mysearch.csv file if no results are returned.
 