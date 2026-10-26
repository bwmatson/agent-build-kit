## From `serial-chat-tests-run-in-parallel/1`

- In tests/session_id_constants.py, the last line of the `duplicated_session_ids` docstring still says only "Any UUID counts, whatever it names". Now that the `sess_` shape is matched too, it could read "Any matching constant counts", so the next reader doesn't think `sess_` strings used for something other than a session id are exempt.
