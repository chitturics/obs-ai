---
 command: inputcsv
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/inputcsv
 title: inputcsv
 download_date: 2026-02-03 09:09:39
---

 # inputcsv

For Splunk Enterprise deployments, loads search results from the specified .csv file, which is not modified. The filename must refer to a relative path in $SPLUNK_HOME/var/run/splunk/csv. If dispatch=true, the path must be in $SPLUNK_HOME/var/run/splunk/dispatch/<job id>.

If the specified file does not exist and the filename does not have an extension, then the Splunk software assumes it has a filename with a .csv extension.

Note: If you run into an issue with the inputcsv command resulting in an error, ensure that your CSV file ends with a BLANK LINE.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The inputcsv command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

#### Appending or replacing results

If the append argument is set to true, you can use the inputcsv command to append the data from the CSV file to the current set of search results. With append=true, you use the inputcsv command later in your search, after the search has returned a set of results.  See Examples.

The append argument is set to false by default. If the append argument is not specified or is set to false, the inputcsv command must be the first command in the search. Data is loaded from the specified CSV file into the search.

#### Working with large CSV files

The WHERE clause allows you to narrow the scope of the search of the inputcsv file.  It restricts the  inputcsv to a smaller number of rows, which can improve search efficiency when you are working with significantly large CSV files.

#### Distributed deployments

The inputcsv command is not compatible with search head pooling and  search head clustering.

The command saves the *.csv file on the local search head in the $SPLUNK_HOME/var/run/splunk/ directory. The *.csv files are not replicated on the other search heads.

#### Strict error handling

Use the strict argument to make inputcsv searches fail whenever they encounter an error condition. You can set this at the system level for all inputcsv and inputlookup searches by changing input_errors_fatal in limits.conf

Note: If you use Splunk Cloud Platform, file a Support ticket to change the input_errors_fatal setting.

Use the strict argument to override the input_errors_fatal setting for an inputcsv search.

#### 1. Load results that contain a specific string

This example loads search results from the $SPLUNK_HOME/var/run/splunk/csv/all.csv file. Those that contain the string error are saved to the $SPLUNK_HOME/var/run/splunk/csv/error.csv file.

#### 2. Load a specific range of results

This example loads results 101 to 600 from either the bar file, if exists, or from the bar.csv file.

#### 3. Specifying which results to load with operators and expressions

You can use comparison operators and Boolean expression to specify which results to load. 
This example loads all of the events from the CSV file $SPLUNK_HOME/var/run/splunk/csv/students.csv and then filters out the events that do not match the WHERE clause, where the values in the age field are greater than 13, less than 19, but not 16. The search returns a count of the remaining search results.

#### 4. Append data from a CSV file to search results

You can use the append argument to append data from a CSV file to a set of search results. In this example the combined data is then output back to the same CSV file.

#### 5. Appending multiple CSV files

You can also append the search results of one CSV file to another CSV file by using the append command and a subsearch. This example uses the eval command to add a field to each set of data to denote which CSV file the data originated from.
 