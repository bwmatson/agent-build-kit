# limit-units-in-progress

Replace the open pull request ceiling with a limit on units in progress: every
unit that has been started and has not finished — building, in review, paused
or held part-way, failed — counts, whether or not it has a pull request yet.
The limit gates only the start of new work, so nothing already begun is ever
stopped short of its pull request.
