# %%
def new_func():
    print("Hello from WSL!")
    for i in range(10):
        pass

    print("Hello from WSL!")


new_func()
# %%
print("My first GitHub commit.")


def test_add():
    assert 1 + 1 == 2


# %%
def count_to_three():
    yield 1
    yield 2
    yield 3


a = count_to_three()
b = next(a)
print(b)
b = next(a)
print(b)
b = next(a)
print(b)
b = next(a)
print(b)
# %%
