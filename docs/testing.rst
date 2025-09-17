Testing
=======

The ``tf`` Framework treats element operations as pure functions.
An element operation takes a dictionary, does something to it, and returns a new dictionary.
The framework does not maintain its own state for element instances.

Instead, the implementing provider is responsible for the "non-pure" parts of the operation such as making API calls to backend services.

This separation of concerns lends itself well to unit testing.

For example, suppose we have a DNS datasource.

.. literalinclude:: examples/datasource-dns.py

Then we might write tests like this:

.. literalinclude:: examples/test-datasource-dns.py

``tf`` consumers are encouraged to write test utilities to reduce boilerplate around diagnostic errors/warning assertions and ``Context`` construction.
