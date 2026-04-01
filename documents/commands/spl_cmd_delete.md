---
 command: delete
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/delete
 title: delete
 download_date: 2026-02-03 09:04:41
---

 # delete

Using the delete command marks all of the events returned by the search as deleted.  Subsequent  searches do not return the marked events. No user, not even a user with admin permissions, is able to view this data after deletion. The delete command does not reclaim disk space.

CAUTION: Removing data is irreversible. If you want to get your data back after the data is deleted, you must re-index the applicable data sources.

You cannot run the delete command in a real-time search to delete events as they arrive.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

The delete command can be accessed only by a user with the "delete_by_keyword" capability. By default, only the "can_delete" role has the ability to delete events.  No other role, including the admin role, has this ability. You should create a special userid that you log on with when you intend to delete indexed data.

To use the delete command, run a search that returns the events you want deleted. Make sure that the search returns ONLY the events that you want to delete, and no other events. After you confirm that the results contain the data that you want to delete, pipe the search to the delete command.

The delete command does not trigger a roll of hot buckets to warm in the affected indexes.

The output of the delete command is a table of the quantity of events removed by the fields splunk_server (the name of the indexer or search head), and index, as well as a rollup record for each server by index "__ALL__".  The quantity of deleted events is in the deleted field.  An errors field is also emitted, which will normally be 0.

#### Delete command restrictions

The delete command does not work in all situations:

#### Permanently removing data from an index

The delete command does not remove the data from your disk space. You must use the clean command from the CLI to permanently remove the data.  The clean command removes all of the data in an index. You cannot select the specific data that you want to remove.  See  Remove indexes and indexed data in Managing Indexers and Clusters of Indexers.

#### 1. Delete events with Social Security numbers

Delete the events from the insecure index that contain strings that look like Social Security numbers. Use the regex  command to identify events that contain the strings that you want to match.

- Run the following search to ensure that you are retrieving the correct data from the  insecure index.
index=insecure | regex _raw = "\d{3}-\d{2}-\d{4}"
- If necessary, adjust the search to retrieve the correct data. Then add the  delete command to the end of the search to delete the events.
index=insecure | regex _raw = "\d{3}-\d{2}-\d{4}" | delete

#### 2. Delete events that contain a specific word

Delete events from the imap index that contain the word invalid.

#### 3. Remove the Search Tutorial events

Remove all of the Splunk Search Tutorial events from your index.

- Login as a user with an administrator role:
  - For Splunk Cloud Platform, the role is sc_admin.
  - For Splunk Enterprise, the role is admin.
- Click Settings > Users and create a new user with the can_delete role.
- Log out as the administrator and log back in as the user with the can_delete role.
- Set the time range picker to All time.
- Run the following search to retrieve all of the Search Tutorial events.   
source=tutorialdata.zip:*
- Confirm that the search is retrieving the correct data.
- Add the delete command to the end of the search criteria and run the search again.
source=tutorialdata.zip:* | delete
The events are removed from the index.
- Log out as the user with the can_delete role.
 