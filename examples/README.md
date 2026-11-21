# Synthetic demonstration

After installing the package, run `lifemate-demo` or
`python examples/mock_request.py`. All example text, schemas, identifiers and
state are handwritten synthetic fixtures.

The real `LLMPlanner`, strict parser, `Agent` and `Controller` execute three
decisions: read a list of mock lights, set the returned light ID to on, and finish.
The mock model client obtains the ID from the tool observation. No language model
or speech recognizer generates the decision. The environment is an in-memory
teaching fixture, not the organizer SDK or a smart-home connection.

Output contains `mode: "mock"`, three explicit false execution flags, the ordered
two actual mock calls, a `mock_state_hash` and decision/tool traces. The hash is
computed from mock state and cannot be submitted as an official state hash.
No output files are written. A smaller decision budget can be explored with
`lifemate-demo --max-steps 1`.
