# `services` package: business logic / use-case orchestration.
#
# Services coordinate the domain (and, in later phases, infrastructure adapters)
# to fulfil a use case. They know the domain but never know about HTTP — routes
# call them, not the other way around.
