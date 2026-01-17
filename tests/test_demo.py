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
def create_multipliers():
    return [lambda x: i * x for i in range(5)]


multipliers = create_multipliers()

# 我们预想输出 0, 2, 4, 6, 8
print([m(2) for m in multipliers])
# %%
